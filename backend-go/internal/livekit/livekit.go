// Package livekit wraps the LiveKit server API used by the non-AI backend: join
// tokens, host moderation (mute / remove) and Egress recording. The AI participant
// (BRSE) and its media pipeline stay in the Python interpreter.
package livekit

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/livekit/protocol/auth"
	lk "github.com/livekit/protocol/livekit"
	"github.com/twitchtv/twirp"
)

const moderationTimeout = 3 * time.Second

func HTTPURL(wsURL string) string {
	u := strings.TrimSpace(wsURL)
	switch {
	case strings.HasPrefix(u, "wss://"):
		return "https://" + strings.TrimPrefix(u, "wss://")
	case strings.HasPrefix(u, "ws://"):
		return "http://" + strings.TrimPrefix(u, "ws://")
	}
	return u
}

type Client struct {
	URL       string
	APIKey    string
	APISecret string
	HTTP      *http.Client
	rooms     lk.RoomService
	egress    lk.Egress
}

func New(wsURL, key, secret string) *Client {
	c := &Client{URL: HTTPURL(wsURL), APIKey: key, APISecret: secret, HTTP: &http.Client{Timeout: 10 * time.Second}}
	c.rooms = lk.NewRoomServiceProtobufClient(c.URL, c.HTTP)
	c.egress = lk.NewEgressProtobufClient(c.URL, c.HTTP)
	return c
}

// JoinToken mirrors livekit_tokens.generate_livekit_token.
func (c *Client) JoinToken(roomName, participantID, participantName, language, kind, identity string, ttl time.Duration, canPublish bool) (string, error) {
	t, f := true, false
	publish := canPublish
	metadata, _ := json.Marshal(map[string]string{
		"participant_id": participantID,
		"language":       language,
		"kind":           kind,
		"room_id":        roomName,
	})
	if identity == "" {
		identity = participantID
	}
	return auth.NewAccessToken(c.APIKey, c.APISecret).
		SetIdentity(identity).
		SetName(participantName).
		SetVideoGrant(&auth.VideoGrant{RoomJoin: true, Room: roomName, CanPublish: &publish, CanSubscribe: &t, CanPublishData: &f}).
		SetMetadata(string(metadata)).
		SetValidFor(ttl).
		ToJWT()
}

func (c *Client) withAuth(ctx context.Context, grant *auth.VideoGrant) (context.Context, error) {
	token, err := auth.NewAccessToken(c.APIKey, c.APISecret).SetVideoGrant(grant).SetValidFor(10 * time.Minute).ToJWT()
	if err != nil {
		return nil, err
	}
	header := make(http.Header)
	header.Set("Authorization", "Bearer "+token)
	return twirp.WithHTTPRequestHeaders(ctx, header)
}

// MuteMicrophone mutes every microphone track of the identity on the SFU. True when confirmed.
func (c *Client) MuteMicrophone(ctx context.Context, roomID, identity string) bool {
	ctx, cancel := context.WithTimeout(ctx, moderationTimeout)
	defer cancel()
	authed, err := c.withAuth(ctx, &auth.VideoGrant{RoomAdmin: true, Room: roomID})
	if err != nil {
		return false
	}
	participant, err := c.rooms.GetParticipant(authed, &lk.RoomParticipantIdentity{Room: roomID, Identity: identity})
	if err != nil {
		return false
	}
	for _, track := range participant.Tracks {
		if track.Source != lk.TrackSource_MICROPHONE || track.Muted {
			continue
		}
		if _, err := c.rooms.MutePublishedTrack(authed, &lk.MuteRoomTrackRequest{Room: roomID, Identity: identity, TrackSid: track.Sid, Muted: true}); err != nil {
			return false
		}
	}
	return true
}

// RemoveParticipant disconnects the identity's media session (best effort).
func (c *Client) RemoveParticipant(ctx context.Context, roomID, identity string) bool {
	ctx, cancel := context.WithTimeout(ctx, moderationTimeout)
	defer cancel()
	authed, err := c.withAuth(ctx, &auth.VideoGrant{RoomAdmin: true, Room: roomID})
	if err != nil {
		return false
	}
	_, err = c.rooms.RemoveParticipant(authed, &lk.RoomParticipantIdentity{Room: roomID, Identity: identity})
	return err == nil
}

// ListParticipants is used by the admin portal (media state only, never media).
func (c *Client) ListParticipants(ctx context.Context, roomID string) ([]*lk.ParticipantInfo, error) {
	authed, err := c.withAuth(ctx, &auth.VideoGrant{RoomAdmin: true, Room: roomID})
	if err != nil {
		return nil, err
	}
	res, err := c.rooms.ListParticipants(authed, &lk.ListParticipantsRequest{Room: roomID})
	if err != nil {
		return nil, err
	}
	return res.Participants, nil
}

func (c *Client) Ping(ctx context.Context) bool {
	authed, err := c.withAuth(ctx, &auth.VideoGrant{RoomList: true})
	if err != nil {
		return false
	}
	_, err = c.rooms.ListRooms(authed, &lk.ListRoomsRequest{})
	return err == nil
}

// ── Egress (server-side Room Composite recording, see archive.recording) ──

const (
	JobStarting = "starting"
	JobActive   = "active"
	JobEnding   = "ending"
	JobComplete = "complete"
	JobFailed   = "failed"
)

type Job struct {
	ID              string
	State           string
	StartedAt       *time.Time
	EndedAt         *time.Time
	SizeBytes       *int64
	DurationSeconds *float64
	Error           string
}

var ErrProviderUnavailable = errors.New("egress start failed")

func fromNS(v int64) *time.Time {
	if v == 0 {
		return nil
	}
	t := time.Unix(0, v).UTC()
	return &t
}

func jobFrom(info *lk.EgressInfo) *Job {
	state := JobFailed
	switch info.Status {
	case lk.EgressStatus_EGRESS_STARTING:
		state = JobStarting
	case lk.EgressStatus_EGRESS_ACTIVE:
		state = JobActive
	case lk.EgressStatus_EGRESS_ENDING:
		state = JobEnding
	case lk.EgressStatus_EGRESS_COMPLETE, lk.EgressStatus_EGRESS_LIMIT_REACHED:
		state = JobComplete
	}
	job := &Job{ID: info.EgressId, State: state, StartedAt: fromNS(info.StartedAt), EndedAt: fromNS(info.EndedAt), Error: info.Error}
	files := info.FileResults
	if len(files) == 0 && info.GetFile() != nil {
		files = []*lk.FileInfo{info.GetFile()}
	}
	if len(files) > 0 {
		if files[0].Size > 0 {
			size := files[0].Size
			job.SizeBytes = &size
		}
		if files[0].Duration > 0 {
			d := float64(files[0].Duration) / 1e9
			job.DurationSeconds = &d
		}
	}
	return job
}

// StartRoomComposite mirrors LiveKitEgressProvider.start: MP4 file output, no upload
// credentials in the request (the egress service uses its own S3 config).
func (c *Client) StartRoomComposite(ctx context.Context, roomName, objectKey, layout string) (*Job, error) {
	authed, err := c.withAuth(ctx, &auth.VideoGrant{RoomRecord: true})
	if err != nil {
		return nil, err
	}
	info, err := c.egress.StartRoomCompositeEgress(authed, &lk.RoomCompositeEgressRequest{
		RoomName: roomName,
		Layout:   layout,
		FileOutputs: []*lk.EncodedFileOutput{{
			FileType:        lk.EncodedFileType_MP4,
			Filepath:        objectKey,
			DisableManifest: true,
		}},
	})
	if err != nil {
		return nil, errors.Join(ErrProviderUnavailable, err)
	}
	return jobFrom(info), nil
}

func (c *Client) StopEgress(ctx context.Context, jobID string) (*Job, error) {
	authed, err := c.withAuth(ctx, &auth.VideoGrant{RoomRecord: true})
	if err != nil {
		return nil, err
	}
	info, err := c.egress.StopEgress(authed, &lk.StopEgressRequest{EgressId: jobID})
	if err != nil {
		// Already ending/complete: the current state is what matters.
		return c.GetEgress(ctx, jobID)
	}
	return jobFrom(info), nil
}

func (c *Client) GetEgress(ctx context.Context, jobID string) (*Job, error) {
	authed, err := c.withAuth(ctx, &auth.VideoGrant{RoomRecord: true})
	if err != nil {
		return nil, err
	}
	res, err := c.egress.ListEgress(authed, &lk.ListEgressRequest{EgressId: jobID})
	if err != nil {
		return nil, err
	}
	if len(res.Items) == 0 {
		return nil, nil
	}
	return jobFrom(res.Items[0]), nil
}
