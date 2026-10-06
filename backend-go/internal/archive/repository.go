package archive

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"meetq/backend-go/internal/platform"
)

const (
	SettingsCol   = "system_settings"
	ArchivesCol   = "meeting_archives"
	RecordingsCol = "meeting_recordings"

	RetentionSettingsID = "meeting_retention"

	ArchiveOpen                = "open"
	ArchiveFinalizing          = "finalizing"
	ArchiveProcessingRecording = "processing_recording"
	ArchiveReady               = "ready"
	ArchivePartial             = "partial"
	ArchiveFailed              = "failed"
	ArchiveDeleting            = "deleting"
	ArchiveDeleted             = "deleted"

	RecStarting   = "starting"
	RecRecording  = "recording"
	RecStopping   = "stopping"
	RecProcessing = "processing"
	RecReady      = "ready"
	RecFailed     = "failed"
)

var (
	ErrRecordingNotFound = errors.New("recording not found")
	ErrArchiveNotFound   = errors.New("archive not found")
)

func ArchiveIDForRoom(roomID string) string {
	suffix := roomID
	if strings.HasPrefix(roomID, "rm_") {
		suffix = roomID[3:]
	}
	return "arc_" + suffix
}

func NewRecordingID() string {
	return "rec_" + platform.RandomHex(8)
}

func PublicRecording(doc map[string]any) map[string]any {
	if doc == nil {
		return nil
	}
	recID, _ := doc["_id"].(string)
	if recID == "" {
		recID, _ = doc["recording_id"].(string)
	}
	out := map[string]any{
		"recording_id": recID,
		"room_id":      doc["room_id"],
		"archive_id":   doc["archive_id"],
		"status":       doc["status"],
		"requested_at": doc["requested_at"],
		"started_at":   doc["started_at"],
		"stopped_at":   doc["stopped_at"],
		"version":      doc["version"],
	}
	if v, ok := doc["duration_seconds"]; ok {
		out["duration_seconds"] = v
	}
	if v, ok := doc["size_bytes"]; ok {
		out["size_bytes"] = v
	}
	if v, ok := doc["stop_reason"]; ok {
		out["stop_reason"] = v
	}
	if v, ok := doc["error_code"]; ok {
		out["error_code"] = v
	}
	if v, ok := doc["stopped_by_name"]; ok {
		out["stopped_by"] = v
	}
	out["started_by"] = map[string]any{
		"participant_id": doc["started_by_participant_id"],
		"display_name":   doc["started_by_name"],
	}
	if out["version"] == nil {
		out["version"] = 1
	}
	return out
}

type Repository struct {
	db                   *mongo.Database
	defaultRetentionDays int
}

func NewRepository(db *mongo.Database, defaultRetention int) *Repository {
	if defaultRetention <= 0 {
		defaultRetention = 7
	}
	return &Repository{
		db:                   db,
		defaultRetentionDays: defaultRetention,
	}
}

func (r *Repository) Enabled() bool {
	return r != nil && r.db != nil
}

func (r *Repository) GetRetentionSettings(ctx context.Context) (map[string]any, error) {
	if !r.Enabled() {
		return map[string]any{
			"default_retention_days": r.defaultRetentionDays,
			"source":                 "default",
		}, nil
	}
	var doc map[string]any
	err := r.db.Collection(SettingsCol).FindOne(ctx, bson.M{"_id": RetentionSettingsID}).Decode(&doc)
	if err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return map[string]any{
				"default_retention_days": r.defaultRetentionDays,
				"source":                 "default",
			}, nil
		}
		return nil, err
	}
	days := r.defaultRetentionDays
	if d, ok := doc["default_retention_days"].(int32); ok {
		days = int(d)
	} else if d, ok := doc["default_retention_days"].(int64); ok {
		days = int(d)
	}
	return map[string]any{
		"default_retention_days": days,
		"updated_at":             doc["updated_at"],
		"updated_by":             doc["updated_by"],
		"source":                 "admin",
	}, nil
}

func (r *Repository) UpdateRetentionSettings(ctx context.Context, days int, updatedBy string) (map[string]any, error) {
	if !r.Enabled() {
		return nil, fmt.Errorf("history unavailable")
	}
	now := platform.NowStr()
	doc := bson.M{
		"default_retention_days": days,
		"updated_at":             now,
		"updated_by":             updatedBy,
	}
	_, err := r.db.Collection(SettingsCol).UpdateOne(
		ctx,
		bson.M{"_id": RetentionSettingsID},
		bson.M{"$set": doc},
		options.UpdateOne().SetUpsert(true),
	)
	if err != nil {
		return nil, err
	}
	doc["source"] = "admin"
	return doc, nil
}

func (r *Repository) ActiveRecording(ctx context.Context, roomID string) (map[string]any, error) {
	if !r.Enabled() {
		return nil, nil
	}
	var doc map[string]any
	err := r.db.Collection(RecordingsCol).FindOne(ctx, bson.M{
		"room_id": roomID,
		"active":  true,
	}).Decode(&doc)
	if err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, nil
		}
		return nil, err
	}
	return doc, nil
}

func (r *Repository) GetRecording(ctx context.Context, recordingID string) (map[string]any, error) {
	if !r.Enabled() {
		return nil, nil
	}
	var doc map[string]any
	err := r.db.Collection(RecordingsCol).FindOne(ctx, bson.M{"_id": recordingID}).Decode(&doc)
	if err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, nil
		}
		return nil, err
	}
	return doc, nil
}

func (r *Repository) ListRecordings(ctx context.Context, roomID string) ([]map[string]any, error) {
	if !r.Enabled() {
		return []map[string]any{}, nil
	}
	cur, err := r.db.Collection(RecordingsCol).Find(
		ctx,
		bson.M{"room_id": roomID},
		options.Find().SetSort(bson.D{{Key: "created_at", Value: 1}}),
	)
	if err != nil {
		return nil, err
	}
	defer cur.Close(ctx)
	var out []map[string]any
	if err := cur.All(ctx, &out); err != nil {
		return nil, err
	}
	return out, nil
}

func (r *Repository) ListAllRecordings(ctx context.Context, status *string, page, pageSize int) ([]map[string]any, int64, error) {
	if !r.Enabled() {
		return []map[string]any{}, 0, nil
	}
	filter := bson.M{}
	if status != nil && *status != "" {
		filter["status"] = *status
	}
	total, err := r.db.Collection(RecordingsCol).CountDocuments(ctx, filter)
	if err != nil {
		return nil, 0, err
	}

	cur, err := r.db.Collection(RecordingsCol).Find(
		ctx,
		filter,
		options.Find().
			SetSort(bson.D{{Key: "created_at", Value: -1}}).
			SetSkip(int64((page-1)*pageSize)).
			SetLimit(int64(pageSize)),
	)
	if err != nil {
		return nil, 0, err
	}
	defer cur.Close(ctx)

	var docs []map[string]any
	if err := cur.All(ctx, &docs); err != nil {
		return nil, 0, err
	}
	return docs, total, nil
}

func (r *Repository) GetArchive(ctx context.Context, archiveID string) (map[string]any, error) {
	if !r.Enabled() {
		return nil, nil
	}
	var doc map[string]any
	err := r.db.Collection(ArchivesCol).FindOne(ctx, bson.M{"_id": archiveID}).Decode(&doc)
	if err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, nil
		}
		return nil, err
	}
	return doc, nil
}

func (r *Repository) GetArchiveByRoomID(ctx context.Context, roomID string) (map[string]any, error) {
	if !r.Enabled() {
		return nil, nil
	}
	var doc map[string]any
	err := r.db.Collection(ArchivesCol).FindOne(ctx, bson.M{"room_id": roomID}).Decode(&doc)
	if err != nil {
		if errors.Is(err, mongo.ErrNoDocuments) {
			return nil, nil
		}
		return nil, err
	}
	return doc, nil
}

func (r *Repository) UpdateArchiveRetention(ctx context.Context, archiveID string, days int, updatedBy string) (map[string]any, error) {
	if !r.Enabled() {
		return nil, fmt.Errorf("history unavailable")
	}
	now := platform.NowUTC()
	expiresAt := now.Add(time.Duration(days) * 24 * time.Hour)
	expiresAtStr := platform.ISO(expiresAt)
	update := bson.M{
		"$set": bson.M{
			"retention_days": days,
			"expires_at":     expiresAtStr,
			"updated_at":     platform.ISO(now),
			"updated_by":     updatedBy,
		},
	}
	res, err := r.db.Collection(ArchivesCol).UpdateOne(ctx, bson.M{"_id": archiveID}, update)
	if err != nil {
		return nil, err
	}
	if res.MatchedCount == 0 {
		return nil, ErrArchiveNotFound
	}
	return r.GetArchive(ctx, archiveID)
}

func (r *Repository) DeleteArchive(ctx context.Context, archiveID string) error {
	if !r.Enabled() {
		return fmt.Errorf("history unavailable")
	}
	res, err := r.db.Collection(ArchivesCol).DeleteOne(ctx, bson.M{"_id": archiveID})
	if err != nil {
		return err
	}
	if res.DeletedCount == 0 {
		return ErrArchiveNotFound
	}
	return nil
}
