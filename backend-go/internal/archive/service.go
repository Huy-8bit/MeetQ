package archive

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/redis/go-redis/v9"
	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"meetq/backend-go/internal/config"
	"meetq/backend-go/internal/livekit"
	"meetq/backend-go/internal/platform"
)

type RecordingError struct {
	Status  int
	Code    string
	Message string
}

func (e *RecordingError) Error() string { return e.Message }

type Service struct {
	Cfg     *config.Config
	Repo    *Repository
	Storage *Storage
	LiveKit *livekit.Client
	Redis   *redis.Client
	Log     *slog.Logger
	Publish func(ctx context.Context, eventType, roomID string, payload any) error
}

func NewService(
	cfg *config.Config,
	repo *Repository,
	storage *Storage,
	lk *livekit.Client,
	r *redis.Client,
	publish func(ctx context.Context, eventType, roomID string, payload any) error,
) *Service {
	return &Service{
		Cfg:     cfg,
		Repo:    repo,
		Storage: storage,
		LiveKit: lk,
		Redis:   r,
		Publish: publish,
	}
}

func (s *Service) Available() bool {
	return s != nil && s.Cfg.MeetingRecordingEnabled && s.Repo.Enabled() && s.Storage != nil && s.LiveKit != nil
}

func (s *Service) Current(ctx context.Context, roomID string) (map[string]any, error) {
	if !s.Repo.Enabled() {
		return nil, nil
	}
	doc, err := s.Repo.ActiveRecording(ctx, roomID)
	if err != nil || doc == nil {
		return nil, err
	}
	return PublicRecording(doc), nil
}

func (s *Service) StopForRoomEnd(ctx context.Context, roomID, reason string) {
	if !s.Available() {
		return
	}
	doc, err := s.Repo.ActiveRecording(ctx, roomID)
	if err != nil || doc == nil {
		return
	}
	recID, _ := doc["_id"].(string)
	if recID != "" {
		_, _ = s.Stop(ctx, roomID, recID, reason, "system")
	}
}

func (s *Service) acquireLock(ctx context.Context, roomID string) (func(), error) {
	key := fmt.Sprintf("brseai:v1:recording:lock:%s", roomID)
	deadline := time.Now().Add(5 * time.Second)
	token := platform.RandomHex(16)
	for time.Now().Before(deadline) {
		ok, err := s.Redis.SetNX(ctx, key, token, 15*time.Second).Result()
		if err == nil && ok {
			return func() {
				_ = s.Redis.Del(context.WithoutCancel(ctx), key).Err()
			}, nil
		}
		select {
		case <-time.After(100 * time.Millisecond):
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
	return nil, &RecordingError{Status: 409, Code: "recording_busy", Message: "Another recording change is in progress. Try again."}
}

func (s *Service) Start(
	ctx context.Context,
	roomID, participantID, displayName, userID string,
	roomLanguages []string,
) (map[string]any, error) {
	if !s.Available() {
		return nil, &RecordingError{Status: 503, Code: "recording_unavailable", Message: "Recording isn't available on this server."}
	}

	unlock, err := s.acquireLock(ctx, roomID)
	if err != nil {
		return nil, err
	}
	defer unlock()

	active, err := s.Repo.ActiveRecording(ctx, roomID)
	if err != nil {
		return nil, err
	}
	if active != nil {
		return PublicRecording(active), nil
	}

	recID := NewRecordingID()
	arcID := ArchiveIDForRoom(roomID)
	objectKey := fmt.Sprintf("%s/%s/recordings/%s.mp4", s.Cfg.MeetingArchivePrefix, roomID, recID)

	now := platform.NowStr()
	doc := bson.M{
		"_id":                       recID,
		"recording_id":              recID,
		"room_id":                   roomID,
		"archive_id":                arcID,
		"status":                    RecStarting,
		"active":                    true,
		"requested_at":              now,
		"started_at":                now,
		"created_at":                now,
		"started_by_participant_id": participantID,
		"started_by_name":           displayName,
		"started_by_user_id":        userID,
		"s3_key":                    objectKey,
		"version":                   1,
	}

	_, err = s.Repo.db.Collection(RecordingsCol).InsertOne(ctx, doc)
	if err != nil {
		return nil, err
	}

	// Update room document has_recording flag
	_, _ = s.Repo.db.Collection("rooms").UpdateOne(ctx, bson.M{"room_id": roomID}, bson.M{"$set": bson.M{"has_recording": true}})

	layout := s.Cfg.RecordingLayout
	if layout == "" {
		layout = "speaker"
	}

	job, err := s.LiveKit.StartRoomComposite(ctx, roomID, objectKey, layout)
	if err != nil {
		_, _ = s.Repo.db.Collection(RecordingsCol).UpdateOne(
			ctx,
			bson.M{"_id": recID},
			bson.M{"$set": bson.M{
				"status":     RecFailed,
				"active":     false,
				"error_code": "egress_failed",
			}},
		)
		return nil, &RecordingError{Status: 502, Code: "recording_failed", Message: "Could not start recording provider"}
	}

	update := bson.M{
		"status":    RecRecording,
		"egress_id": job.ID,
	}
	_, _ = s.Repo.db.Collection(RecordingsCol).UpdateOne(ctx, bson.M{"_id": recID}, bson.M{"$set": update})
	doc["status"] = RecRecording

	if s.Publish != nil {
		_ = s.Publish(ctx, "recording.started", roomID, PublicRecording(doc))
	}

	return PublicRecording(doc), nil
}

func (s *Service) Stop(ctx context.Context, roomID, recordingID, reason, stoppedByName string) (map[string]any, error) {
	if !s.Available() {
		return nil, &RecordingError{Status: 503, Code: "recording_unavailable", Message: "Recording isn't available on this server."}
	}

	unlock, err := s.acquireLock(ctx, roomID)
	if err != nil {
		return nil, err
	}
	defer unlock()

	doc, err := s.Repo.GetRecording(ctx, recordingID)
	if err != nil || doc == nil {
		return nil, &RecordingError{Status: 404, Code: "recording_not_found", Message: "Recording not found."}
	}

	curStatus, _ := doc["status"].(string)
	if curStatus == RecReady || curStatus == RecFailed || curStatus == RecProcessing {
		return PublicRecording(doc), nil
	}

	egressID, _ := doc["egress_id"].(string)
	if egressID != "" {
		_, _ = s.LiveKit.StopEgress(ctx, egressID)
	}

	now := platform.NowStr()
	update := bson.M{
		"status":          RecReady,
		"active":          false,
		"stopped_at":      now,
		"stop_reason":     reason,
		"stopped_by_name": stoppedByName,
	}

	_, _ = s.Repo.db.Collection(RecordingsCol).UpdateOne(
		ctx,
		bson.M{"_id": recordingID},
		bson.M{"$set": update},
	)

	doc["status"] = RecReady
	doc["stopped_at"] = now
	doc["stop_reason"] = reason
	doc["stopped_by_name"] = stoppedByName

	if s.Publish != nil {
		_ = s.Publish(ctx, "recording.stopped", roomID, PublicRecording(doc))
	}

	return PublicRecording(doc), nil
}

// Dummy options import to prevent unused warnings
var _ = options.Find
var _ = errors.New
