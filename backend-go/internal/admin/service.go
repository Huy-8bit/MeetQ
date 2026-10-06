package admin

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"meetq/backend-go/internal/ai"
	"meetq/backend-go/internal/config"
	"meetq/backend-go/internal/history"
	"meetq/backend-go/internal/livekit"
	"meetq/backend-go/internal/models"
	"meetq/backend-go/internal/platform"
	"meetq/backend-go/internal/store"
)

var (
	ErrRoomNotFound = errors.New("room not found")
)

type Service struct {
	Cfg     *config.Config
	Store   *store.RoomStore
	Redis   *redis.Client
	DB      *mongo.Database
	LiveKit *livekit.Client
	AI      *ai.Client
}

func NewService(cfg *config.Config, s *store.RoomStore, r *redis.Client, db *mongo.Database, lk *livekit.Client, aiClient *ai.Client) *Service {
	return &Service{
		Cfg:     cfg,
		Store:   s,
		Redis:   r,
		DB:      db,
		LiveKit: lk,
		AI:      aiClient,
	}
}

func (s *Service) SystemHealth(ctx context.Context) map[string]any {
	redisStatus := "healthy"
	if err := s.Redis.Ping(ctx).Err(); err != nil {
		redisStatus = "unhealthy"
	}

	mongoStatus := "unavailable"
	if s.DB != nil {
		mongoStatus = "healthy"
		if err := s.DB.Client().Ping(ctx, nil); err != nil {
			mongoStatus = "unhealthy"
		}
	}

	livekitStatus := "unavailable"
	if s.LiveKit != nil {
		if s.LiveKit.Ping(ctx) {
			livekitStatus = "healthy"
		} else {
			livekitStatus = "unhealthy"
		}
	}

	components := []map[string]any{
		{"key": "redis", "name": "Redis (state + events)", "status": redisStatus},
		{"key": "mongo", "name": "MongoDB (history + analytics)", "status": mongoStatus},
		{"key": "livekit", "name": "LiveKit (realtime media)", "status": livekitStatus},
	}

	overall := "healthy"
	for _, c := range components {
		if c["status"] == "unhealthy" {
			overall = "degraded"
		}
	}

	return map[string]any{
		"status":       overall,
		"generated_at": platform.NowStr(),
		"components":   components,
	}
}

func (s *Service) GetConfig(ctx context.Context) map[string]any {
	return map[string]any{
		"editable": false,
		"room": []map[string]any{
			{"key": "room_meeting_duration_seconds", "label": "Room duration", "value": s.Cfg.RoomMeetingDurationSeconds, "unit": "seconds", "source": "environment"},
			{"key": "room_max_participants", "label": "Maximum participants", "value": s.Cfg.RoomMaxParticipants, "source": "environment"},
			{"key": "room_token_ttl_seconds", "label": "Participant token lifetime", "value": s.Cfg.RoomTokenTTLSeconds, "unit": "seconds", "source": "environment"},
		},
		"ai": []map[string]any{
			{"key": "openai_realtime_model", "label": "Realtime model", "value": s.Cfg.OpenAIRealtimeModel, "source": "environment"},
			{"key": "openai_realtime_transcription_model", "label": "Transcription model", "value": s.Cfg.OpenAIRealtimeTranscriptionModel, "source": "environment"},
			{"key": "openai_summary_model", "label": "Summary model", "value": s.Cfg.OpenAISummaryModel, "source": "environment"},
			{"key": "meeting_summary_language", "label": "Summary fallback language", "value": s.Cfg.MeetingSummaryLanguage, "source": "environment"},
		},
		"languages": []map[string]any{
			{"code": "vi", "label": "Vietnamese", "enabled": true, "source": "backend constant"},
			{"code": "en", "label": "English", "enabled": true, "source": "backend constant"},
			{"code": "ja", "label": "Japanese", "enabled": true, "source": "backend constant"},
			{"code": "zh", "label": "Chinese", "enabled": true, "source": "backend constant"},
			{"code": "ko", "label": "Korean", "enabled": true, "source": "backend constant"},
		},
	}
}

func (s *Service) scanLiveRoomKeys(ctx context.Context) ([]string, error) {
	var keys []string
	iter := s.Redis.Scan(ctx, 0, "room:*:meta", 500).Iterator()
	for iter.Next(ctx) {
		keys = append(keys, iter.Val())
	}
	return keys, iter.Err()
}

func (s *Service) ListLiveRooms(
	ctx context.Context,
	query, status, aiMode, language *string,
	page, pageSize int,
) (map[string]any, error) {
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 25
	} else if pageSize > 100 {
		pageSize = 100
	}

	keys, err := s.scanLiveRoomKeys(ctx)
	if err != nil {
		return nil, err
	}

	var rows []map[string]any
	for _, key := range keys {
		parts := strings.Split(key, ":")
		if len(parts) != 3 {
			continue
		}
		roomID := parts[1]
		st, err := s.Store.GetRoomState(ctx, roomID)
		if err != nil || st == nil {
			continue
		}

		partsList, _ := s.Store.AllParticipants(ctx, roomID)
		onlineCount := 0
		for _, p := range partsList {
			if !p.IsVirtual && p.Status == "joined" {
				onlineCount++
			}
		}

		rStatus := "live"
		if onlineCount == 0 {
			rStatus = "empty"
		}
		t := platform.ParseTime(st.ExpiresAt)
		if t != nil && !platform.NowUTC().Before(*t) {
			rStatus = "expired"
		}

		if status != nil && *status != "" && *status != rStatus {
			continue
		}
		if aiMode != nil && *aiMode != "" && *aiMode != st.BrseMode {
			continue
		}
		if language != nil && *language != "" {
			matched := false
			for _, l := range st.RoomLanguages {
				if l == *language {
					matched = true
					break
				}
			}
			if !matched {
				continue
			}
		}
		if query != nil && *query != "" {
			q := strings.ToLower(*query)
			title := ""
			if st.Title != nil {
				title = strings.ToLower(*st.Title)
			}
			if !strings.Contains(strings.ToLower(st.RoomID), q) && !strings.Contains(title, q) {
				continue
			}
		}

		rows = append(rows, map[string]any{
			"room_id":             st.RoomID,
			"title":               st.Title,
			"status":              rStatus,
			"ai_mode":             st.BrseMode,
			"brse_enabled":        st.BrseEnabled,
			"room_languages":      st.RoomLanguages,
			"created_at":          st.CreatedAt,
			"expires_at":          st.ExpiresAt,
			"participants_online": onlineCount,
			"participants_total":  len(partsList),
		})
	}

	sort.Slice(rows, func(i, j int) bool {
		return rows[i]["created_at"].(string) > rows[j]["created_at"].(string)
	})

	total := len(rows)
	offset := (page - 1) * pageSize
	items := []map[string]any{}
	if offset < total {
		end := offset + pageSize
		if end > total {
			end = total
		}
		items = rows[offset:end]
	}

	return map[string]any{
		"items":     items,
		"total":     total,
		"page":      page,
		"page_size": pageSize,
	}, nil
}

func (s *Service) GetLiveRoom(ctx context.Context, roomID string) (map[string]any, error) {
	st, err := s.Store.GetRoomState(ctx, roomID)
	if err != nil || st == nil {
		return nil, ErrRoomNotFound
	}

	partsList, _ := s.Store.AllParticipants(ctx, roomID)
	onlineCount := 0
	liveParts := []map[string]any{}
	for _, p := range partsList {
		if p.Status == "joined" && !p.IsVirtual {
			onlineCount++
		}
		liveParts = append(liveParts, map[string]any{
			"participant_id": p.ParticipantID,
			"display_name":   p.DisplayName,
			"role":           p.Role,
			"status":         p.Status,
			"language":       p.Language,
			"joined_at":      p.JoinedAt,
			"is_virtual":     p.IsVirtual,
		})
	}

	rStatus := "live"
	if onlineCount == 0 {
		rStatus = "empty"
	}
	t := platform.ParseTime(st.ExpiresAt)
	if t != nil && !platform.NowUTC().Before(*t) {
		rStatus = "expired"
	}

	return map[string]any{
		"room_id":             st.RoomID,
		"title":               st.Title,
		"status":              rStatus,
		"ai_mode":             st.BrseMode,
		"brse_enabled":        st.BrseEnabled,
		"room_languages":      st.RoomLanguages,
		"created_at":          st.CreatedAt,
		"expires_at":          st.ExpiresAt,
		"participants_online": onlineCount,
		"participants":        liveParts,
	}, nil
}

func (s *Service) GetRoomTimeline(ctx context.Context, roomID string, limit int) (map[string]any, error) {
	if limit < 1 {
		limit = 50
	}
	key := fmt.Sprintf("brseai:v1:ops:events:%s", roomID)
	vals, _ := s.Redis.LRange(ctx, key, 0, int64(limit-1)).Result()
	items := make([]any, 0, len(vals))
	for _, v := range vals {
		var obj any
		if err := json.Unmarshal([]byte(v), &obj); err == nil {
			items = append(items, obj)
		}
	}
	return map[string]any{
		"room_id": roomID,
		"items":   items,
	}, nil
}

func (s *Service) GetRoomTranscript(ctx context.Context, roomID string, kind string, limit int) (map[string]any, error) {
	if limit < 1 {
		limit = 100
	}
	key := store.TranscriptsKey(roomID)
	raws, _ := s.Redis.LRange(ctx, key, -int64(limit), -1).Result()
	lines := make([]any, 0, len(raws))
	for _, r := range raws {
		var obj any
		if err := json.Unmarshal([]byte(r), &obj); err == nil {
			lines = append(lines, obj)
		}
	}
	return map[string]any{
		"room_id": roomID,
		"lines":   lines,
	}, nil
}

func (s *Service) GetOverview(ctx context.Context, todayStart *time.Time) (map[string]any, error) {
	keys, _ := s.scanLiveRoomKeys(ctx)
	health := s.SystemHealth(ctx)

	activeRooms := 0
	openRooms := 0
	onlineParts := 0
	aiRooms := 0

	for _, k := range keys {
		parts := strings.Split(k, ":")
		if len(parts) != 3 {
			continue
		}
		st, _ := s.Store.GetRoomState(ctx, parts[1])
		if st == nil {
			continue
		}
		t := platform.ParseTime(st.ExpiresAt)
		if t != nil && !platform.NowUTC().Before(*t) {
			continue
		}
		openRooms++
		if st.BrseEnabled {
			aiRooms++
		}
		allP, _ := s.Store.AllParticipants(ctx, st.RoomID)
		roomOnline := 0
		for _, p := range allP {
			if p.Status == "joined" && !p.IsVirtual {
				roomOnline++
				onlineParts++
			}
		}
		if roomOnline > 0 {
			activeRooms++
		}
	}

	kpis := map[string]any{
		"active_rooms":        map[string]any{"value": activeRooms, "available": true},
		"open_rooms":          map[string]any{"value": openRooms, "available": true},
		"participants_online": map[string]any{"value": onlineParts, "available": true},
		"ai_enabled_rooms":    map[string]any{"value": aiRooms, "available": true},
		"rooms_with_errors":   map[string]any{"value": 0, "available": true},
	}

	return map[string]any{
		"generated_at":      platform.NowStr(),
		"history_available": s.DB != nil,
		"kpis":              kpis,
		"system_health":     health,
		"live_rooms":        []any{},
		"recent_issues":     []any{},
	}, nil
}

func (s *Service) ListMeetings(
	ctx context.Context,
	query, dateFrom, dateTo, language, aiMode, summaryStatus, status *string,
	page, pageSize int,
) (map[string]any, error) {
	if s.DB == nil {
		return map[string]any{"items": []any{}, "total": 0, "page": page, "page_size": pageSize}, nil
	}
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 25
	} else if pageSize > 100 {
		pageSize = 100
	}

	filter := bson.M{}
	if query != nil && *query != "" {
		re := bson.M{"$regex": "(?i)" + regexp.QuoteMeta(*query)}
		filter["$or"] = bson.A{bson.M{"title": re}, bson.M{"room_id": re}}
	}
	if language != nil && *language != "" {
		filter["room_languages"] = *language
	}
	if aiMode != nil && *aiMode != "" {
		filter["brse_mode"] = *aiMode
	}
	if summaryStatus != nil && *summaryStatus != "" {
		filter["meeting_summary.status"] = *summaryStatus
	}

	total, err := s.DB.Collection(history.Rooms).CountDocuments(ctx, filter)
	if err != nil {
		return nil, err
	}

	cur, err := s.DB.Collection(history.Rooms).Find(
		ctx,
		filter,
		options.Find().
			SetSort(bson.D{{Key: "created_at", Value: -1}}).
			SetSkip(int64((page-1)*pageSize)).
			SetLimit(int64(pageSize)),
	)
	if err != nil {
		return nil, err
	}
	defer cur.Close(ctx)

	var docs []map[string]any
	if err := cur.All(ctx, &docs); err != nil {
		return nil, err
	}

	items := make([]map[string]any, 0, len(docs))
	for _, d := range docs {
		items = append(items, map[string]any{
			"room_id":           d["room_id"],
			"title":             d["title"],
			"created_at":        d["created_at"],
			"meeting_languages": d["room_languages"],
			"brse_mode":         d["brse_mode"],
			"participant_count": d["participant_count_total"],
			"summary_status":    ((d["meeting_summary"] != nil) && (d["meeting_summary"].(map[string]any)["status"] != nil)),
		})
	}

	return map[string]any{
		"items":     items,
		"total":     total,
		"page":      page,
		"page_size": pageSize,
	}, nil
}

func (s *Service) GetMeetingDetail(ctx context.Context, roomID string) (map[string]any, error) {
	if s.DB == nil {
		return nil, ErrRoomNotFound
	}
	var doc map[string]any
	err := s.DB.Collection(history.Rooms).FindOne(ctx, bson.M{"room_id": roomID}).Decode(&doc)
	if err != nil {
		return nil, ErrRoomNotFound
	}
	return doc, nil
}

func (s *Service) GetMeetingTranscripts(ctx context.Context, roomID string, page, pageSize int) (map[string]any, error) {
	return s.getMessages(ctx, roomID, []string{"source", "translated"}, page, pageSize)
}

func (s *Service) GetMeetingRelays(ctx context.Context, roomID string, page, pageSize int) (map[string]any, error) {
	return s.getMessages(ctx, roomID, []string{"relay"}, page, pageSize)
}

func (s *Service) GetMeetingChat(ctx context.Context, roomID string, page, pageSize int) (map[string]any, error) {
	return s.getMessages(ctx, roomID, []string{"chat"}, page, pageSize)
}

func (s *Service) getMessages(ctx context.Context, roomID string, kinds []string, page, pageSize int) (map[string]any, error) {
	if s.DB == nil {
		return map[string]any{"items": []any{}, "total": 0, "page": page, "page_size": pageSize}, nil
	}
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 50
	} else if pageSize > 100 {
		pageSize = 100
	}

	filter := bson.M{
		"room_id": roomID,
		"kind":    bson.M{"$in": kinds},
	}
	total, err := s.DB.Collection(history.Messages).CountDocuments(ctx, filter)
	if err != nil {
		return nil, err
	}

	cur, err := s.DB.Collection(history.Messages).Find(
		ctx,
		filter,
		options.Find().
			SetSort(bson.D{{Key: "created_at", Value: 1}}).
			SetSkip(int64((page-1)*pageSize)).
			SetLimit(int64(pageSize)),
	)
	if err != nil {
		return nil, err
	}
	defer cur.Close(ctx)

	var docs []map[string]any
	if err := cur.All(ctx, &docs); err != nil {
		return nil, err
	}

	return map[string]any{
		"items":     docs,
		"total":     total,
		"page":      page,
		"page_size": pageSize,
	}, nil
}

func (s *Service) GetMeetingSummaries(ctx context.Context, roomID string) (map[string]any, error) {
	if s.DB == nil {
		return map[string]any{"final": nil, "interim": nil}, nil
	}
	cur, err := s.DB.Collection(history.Summaries).Find(ctx, bson.M{"room_id": roomID})
	if err != nil {
		return nil, err
	}
	defer cur.Close(ctx)
	var docs []map[string]any
	_ = cur.All(ctx, &docs)

	res := map[string]any{"final": nil, "interim": nil}
	for _, d := range docs {
		st, _ := d["summary_type"].(string)
		if st != "" {
			res[st] = d
		}
	}
	return res, nil
}

func (s *Service) RegenerateFinalSummary(ctx context.Context, roomID string, language *string) (map[string]any, error) {
	if s.AI == nil || !s.AI.Configured() {
		return nil, &ai.Error{Status: 503, Code: "ai_unavailable", Message: "AI service is unavailable"}
	}
	finalType := "final"
	req := ai.SummaryRequest{
		Type:     &finalType,
		Language: language,
	}
	raw, err := s.AI.GenerateSummary(ctx, roomID, req)
	if err != nil {
		return nil, err
	}
	var res map[string]any
	_ = json.Unmarshal(raw, &res)
	return res, nil
}

func (s *Service) GetMeetingParticipants(ctx context.Context, roomID string) ([]map[string]any, error) {
	if s.DB == nil {
		return []map[string]any{}, nil
	}
	cur, err := s.DB.Collection(history.Participants).Find(ctx, bson.M{"room_id": roomID})
	if err != nil {
		return nil, err
	}
	defer cur.Close(ctx)
	var docs []map[string]any
	if err := cur.All(ctx, &docs); err != nil {
		return nil, err
	}
	return docs, nil
}

func (s *Service) GetAiMetrics(ctx context.Context, window string) (map[string]any, error) {
	return map[string]any{
		"window":       window,
		"generated_at": platform.NowStr(),
		"metrics":      map[string]any{},
	}, nil
}

func (s *Service) GetIssues(ctx context.Context, window string, includeInfo bool) (map[string]any, error) {
	return map[string]any{
		"window":       window,
		"generated_at": platform.NowStr(),
		"items":        []any{},
	}, nil
}

func (s *Service) GetIssueDetail(ctx context.Context, code, window string, page, pageSize int) (map[string]any, error) {
	return map[string]any{
		"code":      code,
		"window":    window,
		"items":     []any{},
		"total":     0,
		"page":      page,
		"page_size": pageSize,
	}, nil
}

func (s *Service) GetAnalytics(ctx context.Context, start, end time.Time, tzOffsetMinutes int) (map[string]any, error) {
	return map[string]any{
		"from":         platform.ISO(start),
		"to":           platform.ISO(end),
		"generated_at": platform.NowStr(),
		"meetings":     []any{},
		"totals":       map[string]any{"meetings": 0, "duration_minutes": 0, "participants": 0},
	}, nil
}

// Dummy models import
var _ = models.DefaultBrseEnabled
