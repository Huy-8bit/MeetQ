package meetings

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"

	"meetq/backend-go/internal/archive"
	"meetq/backend-go/internal/platform"
)

const (
	RoomsCol        = "rooms"
	ParticipantsCol = "room_participants"
	MessagesCol     = "room_messages"
	SummariesCol    = "meeting_summaries"
	MembershipsCol  = "room_memberships"

	ListPageSizeMax          = 50
	ContentPageSize          = 50
	ContentPageSizeMax       = 200
	SearchPageSize           = 20
	GlobalSearchMeetingScope = 200
)

var (
	ErrMeetingNotFound = errors.New("meeting not found")
	ErrMeetingExpired  = errors.New("meeting retention expired")
	ErrMeetingDeleted  = errors.New("meeting deleted")
)

var languageNames = map[string][]string{
	"vi": {"vietnamese", "tiếng việt"},
	"en": {"english"},
	"ja": {"japanese", "日本語"},
	"zh": {"chinese", "中文"},
	"ko": {"korean", "한국어"},
	"fr": {"french", "français"},
	"es": {"spanish", "español"},
}

var summarySections = []struct {
	Field string
	Label string
}{
	{"summary_text", "Overview"},
	{"key_points", "Key points"},
	{"decisions", "Decisions"},
	{"action_items", "Action items"},
	{"risks_blockers", "Risks and blockers"},
	{"open_questions", "Open questions"},
	{"next_steps", "Next steps"},
}

type MeetingAccess struct {
	RoomID     string
	UserID     string
	Room       map[string]any
	Archive    map[string]any
	Membership map[string]any
}

func EncodeCursor(createdAt, messageID string) string {
	raw, _ := json.Marshal([]string{createdAt, messageID})
	return strings.TrimRight(base64.URLEncoding.EncodeToString(raw), "=")
}

func DecodeCursor(cursor string) (string, string, error) {
	if cursor == "" {
		return "", "", nil
	}
	padded := cursor
	if rem := len(cursor) % 4; rem != 0 {
		padded += strings.Repeat("=", 4-rem)
	}
	b, err := base64.URLEncoding.DecodeString(padded)
	if err != nil {
		return "", "", fmt.Errorf("invalid cursor: %w", err)
	}
	var arr []string
	if err := json.Unmarshal(b, &arr); err != nil || len(arr) < 2 {
		return "", "", fmt.Errorf("invalid cursor payload")
	}
	return arr[0], arr[1], nil
}

type Service struct {
	db          *mongo.Database
	archiveRepo *archive.Repository
}

func NewService(db *mongo.Database, repo *archive.Repository) *Service {
	return &Service{
		db:          db,
		archiveRepo: repo,
	}
}

func (s *Service) Enabled() bool {
	return s != nil && s.db != nil
}

func (s *Service) CheckAccess(ctx context.Context, roomID, userID string) error {
	_, err := s.Access(ctx, roomID, userID)
	return err
}

func (s *Service) Access(ctx context.Context, roomID, userID string) (*MeetingAccess, error) {
	if !s.Enabled() || userID == "" {
		return nil, ErrMeetingNotFound
	}

	var arc map[string]any
	if s.archiveRepo != nil && s.archiveRepo.Enabled() {
		arc, _ = s.archiveRepo.GetArchiveByRoomID(ctx, roomID)
	}

	if arc != nil && arc["status"] == archive.ArchiveDeleted {
		return nil, ErrMeetingDeleted
	}

	var membership map[string]any
	_ = s.db.Collection(MembershipsCol).FindOne(ctx, bson.M{"room_id": roomID, "user_id": userID}).Decode(&membership)
	if membership != nil && membership["removed_at"] != nil && membership["removed_at"] != "" {
		return nil, ErrMeetingNotFound
	}

	allowed := membership != nil
	if !allowed && arc != nil {
		if users, ok := arc["participant_user_ids"].([]any); ok {
			for _, u := range users {
				if u == userID {
					allowed = true
					break
				}
			}
		}
	}

	if !allowed {
		cnt, _ := s.db.Collection(ParticipantsCol).CountDocuments(ctx, bson.M{"room_id": roomID, "user_id": userID})
		if cnt > 0 {
			allowed = true
		}
	}

	if !allowed {
		return nil, ErrMeetingNotFound
	}

	if arc != nil {
		if exp, ok := arc["expires_at"].(string); ok && exp != "" {
			t := platform.ParseTime(exp)
			if t != nil && !platform.NowUTC().Before(*t) {
				return nil, ErrMeetingExpired
			}
		}
	}

	var roomDoc map[string]any
	_ = s.db.Collection(RoomsCol).FindOne(ctx, bson.M{"room_id": roomID}).Decode(&roomDoc)
	if roomDoc == nil {
		roomDoc = map[string]any{"room_id": roomID}
	}

	return &MeetingAccess{
		RoomID:     roomID,
		UserID:     userID,
		Room:       roomDoc,
		Archive:    arc,
		Membership: membership,
	}, nil
}

func (s *Service) ListMeetings(
	ctx context.Context,
	userID string,
	page, pageSize int,
	query *string,
	filter, dateRange string,
) (map[string]any, error) {
	if !s.Enabled() {
		return map[string]any{
			"items":     []any{},
			"total":     0,
			"page":      page,
			"page_size": pageSize,
		}, nil
	}

	if pageSize < 1 {
		pageSize = 20
	} else if pageSize > ListPageSizeMax {
		pageSize = ListPageSizeMax
	}
	if page < 1 {
		page = 1
	}

	now := platform.NowUTC()
	clauses := bson.A{
		bson.M{"member_user_ids": userID},
		bson.M{
			"$or": bson.A{
				bson.M{"archive_expires_at_dt": nil},
				bson.M{"archive_expires_at_dt": bson.M{"$gt": now}},
			},
		},
	}

	switch filter {
	case "created":
		clauses = append(clauses, bson.M{"created_by_user_id": userID})
	case "recorded":
		clauses = append(clauses, bson.M{"has_recording": true})
	case "summary":
		clauses = append(clauses, bson.M{"meeting_summary.status": "completed"})
	}

	var days int
	hasDays := false
	switch dateRange {
	case "today":
		days = 0
		hasDays = true
	case "7d":
		days = 7
		hasDays = true
	case "30d":
		days = 30
		hasDays = true
	}
	if hasDays {
		todayStart := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
		since := todayStart.AddDate(0, 0, -days)
		clauses = append(clauses, bson.M{"history_sort_at_dt": bson.M{"$gte": since}})
	}

	if query != nil && strings.TrimSpace(*query) != "" {
		q := strings.TrimSpace(*query)
		rePattern := "(?i)" + regexp.QuoteMeta(q)
		lowered := strings.ToLower(q)
		var matchedCodes []string
		for code, names := range languageNames {
			if lowered == code {
				matchedCodes = append(matchedCodes, code)
				continue
			}
			for _, n := range names {
				if strings.Contains(lowered, n) {
					matchedCodes = append(matchedCodes, code)
					break
				}
			}
		}

		orOpts := bson.A{
			bson.M{"title": bson.M{"$regex": rePattern}},
			bson.M{"room_id": bson.M{"$regex": rePattern}},
			bson.M{"participant_summaries.display_name": bson.M{"$regex": rePattern}},
		}
		if len(matchedCodes) > 0 {
			orOpts = append(orOpts, bson.M{"room_languages": bson.M{"$in": matchedCodes}})
		}
		clauses = append(clauses, bson.M{"$or": orOpts})
	}

	mongoQuery := bson.M{"$and": clauses}
	total, err := s.db.Collection(RoomsCol).CountDocuments(ctx, mongoQuery)
	if err != nil {
		return nil, err
	}

	cur, err := s.db.Collection(RoomsCol).Find(
		ctx,
		mongoQuery,
		options.Find().
			SetSort(bson.D{{Key: "history_sort_at_dt", Value: -1}, {Key: "room_id", Value: 1}}).
			SetSkip(int64((page-1)*pageSize)).
			SetLimit(int64(pageSize)),
	)
	if err != nil {
		return nil, err
	}
	defer cur.Close(ctx)

	var rooms []map[string]any
	if err := cur.All(ctx, &rooms); err != nil {
		return nil, err
	}

	roomIDs := make([]string, 0, len(rooms))
	for _, r := range rooms {
		if id, ok := r["room_id"].(string); ok && id != "" {
			roomIDs = append(roomIDs, id)
		}
	}

	archivesMap := make(map[string]map[string]any)
	if len(roomIDs) > 0 && s.archiveRepo != nil && s.archiveRepo.Enabled() {
		acur, err := s.db.Collection(archive.ArchivesCol).Find(ctx, bson.M{"room_id": bson.M{"$in": roomIDs}})
		if err == nil {
			defer acur.Close(ctx)
			var alist []map[string]any
			if err := acur.All(ctx, &alist); err == nil {
				for _, a := range alist {
					if id, ok := a["room_id"].(string); ok {
						archivesMap[id] = a
					}
				}
			}
		}
	}

	membershipsMap := make(map[string]map[string]any)
	if len(roomIDs) > 0 {
		mcur, err := s.db.Collection(MembershipsCol).Find(ctx, bson.M{"user_id": userID, "room_id": bson.M{"$in": roomIDs}})
		if err == nil {
			defer mcur.Close(ctx)
			var mlist []map[string]any
			if err := mcur.All(ctx, &mlist); err == nil {
				for _, m := range mlist {
					if id, ok := m["room_id"].(string); ok {
						membershipsMap[id] = m
					}
				}
			}
		}
	}

	items := make([]map[string]any, 0, len(rooms))
	for _, room := range rooms {
		rid, _ := room["room_id"].(string)
		items = append(items, s.meetingRow(room, archivesMap[rid], membershipsMap[rid], userID))
	}

	return map[string]any{
		"items":     items,
		"total":     total,
		"page":      page,
		"page_size": pageSize,
	}, nil
}

func (s *Service) meetingRow(
	room map[string]any,
	arc map[string]any,
	membership map[string]any,
	userID string,
) map[string]any {
	var terminal bool
	if st, ok := room["status_summary"].(map[string]any); ok {
		if term, ok := st["terminal"].(bool); ok && term {
			terminal = true
		}
	}
	if arc != nil && arc["ended_at"] != nil && arc["ended_at"] != "" {
		terminal = true
	}

	meetingStartedAt := strOrFallback(
		arc, "meeting_started_at",
		strOrFallback(room, "activated_at", strOrFallback(room, "created_at", "")),
	)
	endedAt := ""
	if terminal {
		endedAt = strOrFallback(arc, "ended_at", strOrFallback(room, "ended_at", ""))
	}

	duration := int64(0)
	if meetingStartedAt != "" && endedAt != "" {
		st := platform.ParseTime(meetingStartedAt)
		et := platform.ParseTime(endedAt)
		if st != nil && et != nil {
			duration = int64(et.Sub(*st).Seconds())
		}
	}

	meetingState := "live"
	if terminal {
		meetingState = "ended"
	}

	langs := []any{}
	if rl, ok := room["room_languages"].([]any); ok && len(rl) > 0 {
		langs = rl
	} else if arc != nil {
		if al, ok := arc["room_languages"].([]any); ok {
			langs = al
		}
	}

	var recSummary map[string]any
	if arc != nil && arc["recording_summary"] != nil {
		recSummary, _ = arc["recording_summary"].(map[string]any)
	} else if hasRec, _ := room["has_recording"].(bool); hasRec {
		recStatus := "recording"
		if terminal {
			recStatus = "processing"
		}
		recSummary = map[string]any{
			"status":   recStatus,
			"segments": []any{},
		}
	} else {
		recSummary = map[string]any{
			"status":   "none",
			"segments": []any{},
		}
	}

	pCount := int64(0)
	if jUsers, ok := room["joined_user_ids"].([]any); ok && len(jUsers) > 0 {
		pCount = int64(len(jUsers))
	} else if arc != nil && arc["participant_count"] != nil {
		if c, ok := arc["participant_count"].(int64); ok {
			pCount = c
		} else if c, ok := arc["participant_count"].(int32); ok {
			pCount = int64(c)
		}
	}

	var summaryStatus any
	if ms, ok := room["meeting_summary"].(map[string]any); ok {
		summaryStatus = ms["status"]
	}

	myRole := "participant"
	if membership != nil {
		if r, ok := membership["role"].(string); ok && r != "" {
			myRole = r
		}
	}

	createdByUser, _ := room["created_by_user_id"].(string)

	row := map[string]any{
		"room_id":            room["room_id"],
		"meeting_state":      meetingState,
		"title":              room["title"],
		"room_languages":     langs,
		"created_at":         room["created_at"],
		"meeting_started_at": meetingStartedAt,
		"participant_count":  pCount,
		"recording":          recSummary,
		"summary_status":     summaryStatus,
		"my_role":            myRole,
		"created_by_me":      createdByUser != "" && createdByUser == userID,
	}

	if endedAt != "" {
		row["ended_at"] = endedAt
		row["duration_seconds"] = duration
	} else {
		row["ended_at"] = nil
		row["duration_seconds"] = nil
	}

	if arc != nil {
		row["archive_id"] = arc["_id"]
		row["status"] = arc["status"]
		row["expires_at"] = arc["expires_at"]
		row["retention_days"] = arc["retention_days"]
	} else {
		row["archive_id"] = nil
		row["status"] = nil
		row["expires_at"] = nil
		row["retention_days"] = nil
	}

	return row
}

func (s *Service) Detail(ctx context.Context, access *MeetingAccess) (map[string]any, error) {
	roomID := access.RoomID
	recordings := []map[string]any{}
	if s.archiveRepo != nil && s.archiveRepo.Enabled() {
		recs, _ := s.archiveRepo.ListRecordings(ctx, roomID)
		if recs != nil {
			recordings = recs
		}
	}

	participants, err := s.Participants(ctx, access)
	if err != nil {
		return nil, err
	}

	counts := map[string]int64{
		"transcript": 0,
		"relay":      0,
		"chat":       0,
	}
	counts["transcript"], _ = s.db.Collection(MessagesCol).CountDocuments(ctx, bson.M{"room_id": roomID, "kind": bson.M{"$in": bson.A{"source", "translated"}}})
	counts["relay"], _ = s.db.Collection(MessagesCol).CountDocuments(ctx, bson.M{"room_id": roomID, "kind": "relay"})
	counts["chat"], _ = s.db.Collection(MessagesCol).CountDocuments(ctx, bson.M{"room_id": roomID, "kind": "chat"})

	var summaryDoc map[string]any
	_ = s.db.Collection(SummariesCol).FindOne(ctx, bson.M{"room_id": roomID, "summary_type": "final"}).Decode(&summaryDoc)

	cur, _ := s.db.Collection(MembershipsCol).Find(ctx, bson.M{"room_id": roomID, "role": bson.M{"$in": bson.A{"host", "co_host"}}})
	var hostName *string
	var coHosts []string
	if cur != nil {
		defer cur.Close(ctx)
		var mlist []map[string]any
		_ = cur.All(ctx, &mlist)
		for _, m := range mlist {
			name, _ := m["display_name"].(string)
			role, _ := m["role"].(string)
			if role == "host" && hostName == nil {
				hostName = &name
			} else if role == "co_host" {
				if m["removed_at"] == nil || m["removed_at"] == "" {
					coHosts = append(coHosts, name)
				}
			}
		}
	}

	meetingRow := s.meetingRow(access.Room, access.Archive, access.Membership, access.UserID)
	meetingRow["brse_enabled"] = access.Room["brse_enabled"]
	meetingRow["relay_mode"] = access.Room["brse_output_mode"]
	meetingRow["password_protected"] = access.Room["password_required"] == true
	meetingRow["host"] = hostName
	meetingRow["co_hosts"] = coHosts
	if summaryDoc != nil {
		if st, ok := summaryDoc["status"].(string); ok {
			meetingRow["summary_status"] = st
		}
	}

	return map[string]any{
		"meeting":      meetingRow,
		"recordings":   recordings,
		"participants": participants,
		"counts":       counts,
		"summary":      sanitizeMongoDoc(summaryDoc),
	}, nil
}

func (s *Service) Participants(ctx context.Context, access *MeetingAccess) ([]map[string]any, error) {
	roomID := access.RoomID
	cur, err := s.db.Collection(ParticipantsCol).Find(ctx, bson.M{"room_id": roomID, "is_virtual": bson.M{"$ne": true}})
	if err != nil {
		return nil, err
	}
	defer cur.Close(ctx)

	var docs []map[string]any
	if err := cur.All(ctx, &docs); err != nil {
		return nil, err
	}

	mcur, _ := s.db.Collection(MembershipsCol).Find(ctx, bson.M{"room_id": roomID})
	memberships := make(map[string]map[string]any)
	if mcur != nil {
		defer mcur.Close(ctx)
		var mlist []map[string]any
		_ = mcur.All(ctx, &mlist)
		for _, m := range mlist {
			if uid, ok := m["user_id"].(string); ok {
				memberships[uid] = m
			}
		}
	}

	sort.Slice(docs, func(i, j int) bool {
		ti := strOrFallback(docs[i], "first_joined_at", strOrFallback(docs[i], "last_joined_at", ""))
		tj := strOrFallback(docs[j], "first_joined_at", strOrFallback(docs[j], "last_joined_at", ""))
		return ti < tj
	})

	people := make(map[string]map[string]any)
	order := make([]string, 0)
	for _, doc := range docs {
		if k, _ := doc["kind"].(string); k != "" && k != "human" {
			continue
		}
		userID, _ := doc["user_id"].(string)
		partID, _ := doc["participant_id"].(string)
		key := userID
		if key == "" {
			key = partID
		}
		if key == "" {
			continue
		}

		joined := strOrFallback(doc, "first_joined_at", strOrFallback(doc, "last_joined_at", strOrFallback(doc, "joined_at", "")))
		left := strOrFallback(doc, "last_left_at", strOrFallback(doc, "left_at", ""))

		person, exists := people[key]
		if !exists {
			var role any
			removed := false
			if mem, ok := memberships[userID]; ok && mem != nil {
				role = mem["role"]
				removed = mem["removed_at"] != nil && mem["removed_at"] != ""
			}
			people[key] = map[string]any{
				"participant_id": partID,
				"display_name":   doc["display_name"],
				"language":       doc["language"],
				"kind":           "human",
				"role":           role,
				"removed":        removed,
				"joined_at":      joined,
				"left_at":        left,
				"is_you":         userID != "" && userID == access.UserID,
			}
			order = append(order, key)
		} else {
			if doc["display_name"] != nil {
				person["display_name"] = doc["display_name"]
			}
			if doc["language"] != nil {
				person["language"] = doc["language"]
			}
			if joined != "" && (person["joined_at"] == "" || joined < person["joined_at"].(string)) {
				person["joined_at"] = joined
			}
			if left != "" && (person["left_at"] == "" || left > person["left_at"].(string)) {
				person["left_at"] = left
			}
		}
	}

	result := make([]map[string]any, 0, len(order))
	for _, k := range order {
		result = append(result, people[k])
	}
	return result, nil
}

func (s *Service) paginateMessages(
	ctx context.Context,
	roomID string,
	kinds []string,
	cursor, before, start *string,
	limit int,
) ([]map[string]any, *string, *string, error) {
	if limit < 1 {
		limit = ContentPageSize
	} else if limit > ContentPageSizeMax {
		limit = ContentPageSizeMax
	}

	base := bson.M{"room_id": roomID, "kind": bson.M{"$in": kinds}}

	if before != nil && *before != "" {
		createdAt, messageID, err := DecodeCursor(*before)
		if err != nil {
			return nil, nil, nil, err
		}
		query := bson.M{
			"$and": bson.A{
				base,
				bson.M{
					"$or": bson.A{
						bson.M{"created_at": bson.M{"$lt": createdAt}},
						bson.M{"created_at": createdAt, "message_id": bson.M{"$lt": messageID}},
					},
				},
			},
		}
		cur, err := s.db.Collection(MessagesCol).Find(
			ctx,
			query,
			options.Find().
				SetSort(bson.D{{Key: "created_at", Value: -1}, {Key: "message_id", Value: -1}}).
				SetLimit(int64(limit+1)),
		)
		if err != nil {
			return nil, nil, nil, err
		}
		defer cur.Close(ctx)
		var docs []map[string]any
		if err := cur.All(ctx, &docs); err != nil {
			return nil, nil, nil, err
		}
		hasMore := len(docs) > limit
		if hasMore {
			docs = docs[:limit]
		}
		// reverse back to chronological
		for i, j := 0, len(docs)-1; i < j; i, j = i+1, j-1 {
			docs[i], docs[j] = docs[j], docs[i]
		}
		var nextCursor, prevCursor *string
		if len(docs) > 0 {
			nc := EncodeCursor(strOrFallback(docs[len(docs)-1], "created_at", ""), strOrFallback(docs[len(docs)-1], "message_id", ""))
			nextCursor = &nc
		}
		if len(docs) > 0 && hasMore {
			pc := EncodeCursor(strOrFallback(docs[0], "created_at", ""), strOrFallback(docs[0], "message_id", ""))
			prevCursor = &pc
		}
		return docs, nextCursor, prevCursor, nil
	}

	query := bson.M{"room_id": roomID, "kind": bson.M{"$in": kinds}}
	var anchorCreatedAt, anchorMessageID string
	isStart := false
	if start != nil && *start != "" {
		c, m, err := DecodeCursor(*start)
		if err != nil {
			return nil, nil, nil, err
		}
		anchorCreatedAt, anchorMessageID = c, m
		isStart = true
	} else if cursor != nil && *cursor != "" {
		c, m, err := DecodeCursor(*cursor)
		if err != nil {
			return nil, nil, nil, err
		}
		anchorCreatedAt, anchorMessageID = c, m
	}

	if anchorCreatedAt != "" {
		op := "$gt"
		if isStart {
			op = "$gte"
		}
		query = bson.M{
			"$and": bson.A{
				base,
				bson.M{
					"$or": bson.A{
						bson.M{"created_at": bson.M{"$gt": anchorCreatedAt}},
						bson.M{"created_at": anchorCreatedAt, "message_id": bson.M{op: anchorMessageID}},
					},
				},
			},
		}
	}

	cur, err := s.db.Collection(MessagesCol).Find(
		ctx,
		query,
		options.Find().
			SetSort(bson.D{{Key: "created_at", Value: 1}, {Key: "message_id", Value: 1}}).
			SetLimit(int64(limit+1)),
	)
	if err != nil {
		return nil, nil, nil, err
	}
	defer cur.Close(ctx)

	var docs []map[string]any
	if err := cur.All(ctx, &docs); err != nil {
		return nil, nil, nil, err
	}
	hasMore := len(docs) > limit
	if hasMore {
		docs = docs[:limit]
	}

	var nextCursor, prevCursor *string
	if len(docs) > 0 && hasMore {
		nc := EncodeCursor(strOrFallback(docs[len(docs)-1], "created_at", ""), strOrFallback(docs[len(docs)-1], "message_id", ""))
		nextCursor = &nc
	}
	if len(docs) > 0 && isStart {
		pc := EncodeCursor(strOrFallback(docs[0], "created_at", ""), strOrFallback(docs[0], "message_id", ""))
		prevCursor = &pc
	}
	return docs, nextCursor, prevCursor, nil
}

func (s *Service) Transcript(
	ctx context.Context,
	access *MeetingAccess,
	cursor, before, start *string,
	limit int,
) (map[string]any, error) {
	roomID := access.RoomID
	cnt, _ := s.db.Collection(MessagesCol).CountDocuments(ctx, bson.M{"room_id": roomID, "kind": "source"})
	kinds := []string{"source"}
	if cnt == 0 {
		kinds = []string{"source", "translated"}
	}

	docs, nextCursor, prevCursor, err := s.paginateMessages(ctx, roomID, kinds, cursor, before, start, limit)
	if err != nil {
		return nil, err
	}

	utteranceIDs := make([]string, 0)
	for _, d := range docs {
		if uid, ok := d["utterance_id"].(string); ok && uid != "" {
			utteranceIDs = append(utteranceIDs, uid)
		}
	}

	translationsMap := make(map[string][]map[string]string)
	if len(utteranceIDs) > 0 && len(kinds) == 1 && kinds[0] == "source" {
		tcur, err := s.db.Collection(MessagesCol).Find(
			ctx,
			bson.M{
				"room_id":      roomID,
				"utterance_id": bson.M{"$in": utteranceIDs},
				"kind":         bson.M{"$in": bson.A{"translated", "relay"}},
			},
		)
		if err == nil {
			defer tcur.Close(ctx)
			var tdocs []map[string]any
			if err := tcur.All(ctx, &tdocs); err == nil {
				for _, td := range tdocs {
					uid, _ := td["utterance_id"].(string)
					lang, _ := td["target_lang"].(string)
					text := strOrFallback(td, "translated_text", strOrFallback(td, "brse_text", strOrFallback(td, "text", "")))
					if text != "" && uid != "" {
						bucket := translationsMap[uid]
						exists := false
						for _, b := range bucket {
							if b["language"] == lang && b["text"] == text {
								exists = true
								break
							}
						}
						if !exists {
							translationsMap[uid] = append(bucket, map[string]string{
								"language": lang,
								"text":     text,
							})
						}
					}
				}
			}
		}
	}

	items := make([]map[string]any, 0, len(docs))
	for _, d := range docs {
		uid, _ := d["utterance_id"].(string)
		cur := EncodeCursor(strOrFallback(d, "created_at", ""), strOrFallback(d, "message_id", ""))
		text := strOrFallback(d, "source_text", strOrFallback(d, "text", ""))
		items = append(items, map[string]any{
			"message_id":   d["message_id"],
			"cursor":       cur,
			"kind":         d["kind"],
			"created_at":   d["created_at"],
			"speaker_name": d["display_name"],
			"language":     strOrFallback(d, "language", strOrFallback(d, "src_lang", "")),
			"text":         text,
			"translations": translationsMap[uid],
		})
	}

	return map[string]any{
		"items":       items,
		"next_cursor": nextCursor,
		"prev_cursor": prevCursor,
	}, nil
}

func (s *Service) Relay(
	ctx context.Context,
	access *MeetingAccess,
	cursor, before, start *string,
	limit int,
) (map[string]any, error) {
	docs, nextCursor, prevCursor, err := s.paginateMessages(ctx, access.RoomID, []string{"relay"}, cursor, before, start, limit)
	if err != nil {
		return nil, err
	}

	items := make([]map[string]any, 0, len(docs))
	for _, d := range docs {
		cur := EncodeCursor(strOrFallback(d, "created_at", ""), strOrFallback(d, "message_id", ""))
		srcText := strOrFallback(d, "source_text", "")
		var srcPtr *string
		if srcText != "" {
			srcPtr = &srcText
		}
		items = append(items, map[string]any{
			"message_id":      d["message_id"],
			"cursor":          cur,
			"created_at":      d["created_at"],
			"speaker_name":    d["display_name"],
			"source_language": strOrFallback(d, "src_lang", strOrFallback(d, "language", "")),
			"target_language": d["target_lang"],
			"source_text":     srcPtr,
			"translated_text": strOrFallback(d, "brse_text", strOrFallback(d, "translated_text", strOrFallback(d, "text", ""))),
		})
	}

	return map[string]any{
		"items":       items,
		"next_cursor": nextCursor,
		"prev_cursor": prevCursor,
	}, nil
}

func (s *Service) Chat(
	ctx context.Context,
	access *MeetingAccess,
	cursor, before, start *string,
	limit int,
) (map[string]any, error) {
	docs, nextCursor, prevCursor, err := s.paginateMessages(ctx, access.RoomID, []string{"chat"}, cursor, before, start, limit)
	if err != nil {
		return nil, err
	}

	items := make([]map[string]any, 0, len(docs))
	for _, d := range docs {
		cur := EncodeCursor(strOrFallback(d, "created_at", ""), strOrFallback(d, "message_id", ""))
		transList := []any{}
		if tl, ok := d["translations"].([]any); ok {
			for _, item := range tl {
				if m, ok := item.(map[string]any); ok && m["text"] != nil && m["text"] != "" {
					transList = append(transList, m)
				}
			}
		}
		items = append(items, map[string]any{
			"message_id":   d["message_id"],
			"cursor":       cur,
			"created_at":   d["created_at"],
			"sender_name":  d["display_name"],
			"language":     d["language"],
			"text":         strOrFallback(d, "text", ""),
			"translations": transList,
		})
	}

	return map[string]any{
		"items":       items,
		"next_cursor": nextCursor,
		"prev_cursor": prevCursor,
	}, nil
}

func (s *Service) SearchMeeting(
	ctx context.Context,
	access *MeetingAccess,
	query string,
	page, pageSize int,
) (map[string]any, error) {
	titles := map[string]string{access.RoomID: strOrFallback(access.Room, "title", "")}
	return s.search(ctx, []string{access.RoomID}, titles, query, page, pageSize)
}

func (s *Service) SearchAll(
	ctx context.Context,
	userID, query string,
	page, pageSize int,
) (map[string]any, error) {
	now := platform.NowUTC()
	cur, err := s.db.Collection(RoomsCol).Find(
		ctx,
		bson.M{
			"$and": bson.A{
				bson.M{"member_user_ids": userID},
				bson.M{
					"$or": bson.A{
						bson.M{"archive_expires_at_dt": nil},
						bson.M{"archive_expires_at_dt": bson.M{"$gt": now}},
					},
				},
			},
		},
		options.Find().
			SetProjection(bson.M{"room_id": 1, "title": 1}).
			SetSort(bson.D{{Key: "history_sort_at_dt", Value: -1}, {Key: "room_id", Value: 1}}).
			SetLimit(GlobalSearchMeetingScope),
	)
	if err != nil {
		return nil, err
	}
	defer cur.Close(ctx)

	var rooms []map[string]any
	if err := cur.All(ctx, &rooms); err != nil {
		return nil, err
	}

	// Filter out rooms where user was removed
	mcur, _ := s.db.Collection(MembershipsCol).Find(ctx, bson.M{
		"user_id":    userID,
		"removed_at": bson.M{"$ne": nil},
	})
	removed := make(map[string]bool)
	if mcur != nil {
		defer mcur.Close(ctx)
		var mlist []map[string]any
		_ = mcur.All(ctx, &mlist)
		for _, m := range mlist {
			if rid, ok := m["room_id"].(string); ok {
				removed[rid] = true
			}
		}
	}

	titles := make(map[string]string)
	roomIDs := make([]string, 0)
	for _, r := range rooms {
		rid, _ := r["room_id"].(string)
		if rid != "" && !removed[rid] {
			titles[rid] = strOrFallback(r, "title", "")
			roomIDs = append(roomIDs, rid)
		}
	}

	if len(roomIDs) == 0 {
		return map[string]any{
			"items":     []any{},
			"total":     0,
			"page":      page,
			"page_size": pageSize,
			"query":     query,
		}, nil
	}

	return s.search(ctx, roomIDs, titles, query, page, pageSize)
}

func (s *Service) search(
	ctx context.Context,
	roomIDs []string,
	titles map[string]string,
	query string,
	page, pageSize int,
) (map[string]any, error) {
	if pageSize < 1 {
		pageSize = SearchPageSize
	} else if pageSize > 50 {
		pageSize = 50
	}
	if page < 1 {
		page = 1
	}

	pattern, err := CompileQuery(query)
	if err != nil {
		return nil, err
	}
	rePattern := "(?i)" + regexp.QuoteMeta(query)

	summaryOr := bson.A{}
	for _, sec := range summarySections {
		summaryOr = append(summaryOr, bson.M{sec.Field: bson.M{"$regex": rePattern}})
	}
	summaryOr = append(summaryOr, bson.M{"participant_summary.summary": bson.M{"$regex": rePattern}})

	scur, err := s.db.Collection(SummariesCol).Find(ctx, bson.M{
		"room_id":      bson.M{"$in": roomIDs},
		"summary_type": "final",
		"status":       "completed",
		"$or":          summaryOr,
	})
	summaryHits := make([]map[string]any, 0)
	if err == nil {
		defer scur.Close(ctx)
		var summaries []map[string]any
		_ = scur.All(ctx, &summaries)
		for _, sm := range summaries {
			rid, _ := sm["room_id"].(string)
			summaryHits = append(summaryHits, s.summaryHits(sm, pattern, titles[rid])...)
		}
	}

	messageTextOr := bson.A{}
	for _, f := range []string{"text", "source_text", "translated_text", "brse_text", "translations.text"} {
		messageTextOr = append(messageTextOr, bson.M{f: bson.M{"$regex": rePattern}})
	}

	messageQuery := bson.M{
		"room_id": bson.M{"$in": roomIDs},
		"kind":    bson.M{"$in": bson.A{"source", "translated", "relay", "chat"}},
		"$or":     messageTextOr,
	}

	messageTotal, err := s.db.Collection(MessagesCol).CountDocuments(ctx, messageQuery)
	if err != nil {
		return nil, err
	}

	total := int64(len(summaryHits)) + messageTotal
	offset := (page - 1) * pageSize

	items := make([]map[string]any, 0, pageSize)
	if offset < len(summaryHits) {
		end := offset + pageSize
		if end > len(summaryHits) {
			end = len(summaryHits)
		}
		items = append(items, summaryHits[offset:end]...)
	}

	remaining := pageSize - len(items)
	if remaining > 0 {
		skip := offset - len(summaryHits)
		if skip < 0 {
			skip = 0
		}
		mcur, err := s.db.Collection(MessagesCol).Find(
			ctx,
			messageQuery,
			options.Find().
				SetSort(bson.D{{Key: "created_at", Value: 1}, {Key: "message_id", Value: 1}}).
				SetSkip(int64(skip)).
				SetLimit(int64(remaining)),
		)
		if err == nil {
			defer mcur.Close(ctx)
			var docs []map[string]any
			if err := mcur.All(ctx, &docs); err == nil {
				msgHits := s.messageHits(ctx, docs, pattern, titles)
				items = append(items, msgHits...)
			}
		}
	}

	return map[string]any{
		"items":     items,
		"total":     total,
		"page":      page,
		"page_size": pageSize,
		"query":     query,
	}, nil
}

func (s *Service) summaryHits(summary map[string]any, pattern *regexp.Regexp, title string) []map[string]any {
	hits := make([]map[string]any, 0)
	rid, _ := summary["room_id"].(string)
	sumID, _ := summary["summary_id"].(string)

	for _, sec := range summarySections {
		val := summary[sec.Field]
		if val == nil {
			continue
		}
		var texts []string
		if str, ok := val.(string); ok {
			texts = []string{str}
		} else if arr, ok := val.([]any); ok {
			for _, item := range arr {
				if s, ok := item.(string); ok {
					texts = append(texts, s)
				}
			}
		}

		for _, txt := range texts {
			if pattern.MatchString(txt) {
				snip, highlights := Snippet(txt, pattern)
				hits = append(hits, map[string]any{
					"meeting_id":     rid,
					"meeting_title":  title,
					"source_type":    "summary",
					"section":        sec.Label,
					"timestamp":      summary["generated_at"],
					"speaker":        nil,
					"language":       summary["summary_language"],
					"text":           snip,
					"highlights":     highlights,
					"source_item_id": sumID,
					"cursor":         nil,
				})
				break
			}
		}
	}

	return hits
}

func (s *Service) messageHits(
	ctx context.Context,
	docs []map[string]any,
	pattern *regexp.Regexp,
	titles map[string]string,
) []map[string]any {
	hits := make([]map[string]any, 0, len(docs))
	for _, doc := range docs {
		rid, _ := doc["room_id"].(string)
		k, _ := doc["kind"].(string)
		sourceType := "transcript"
		if k == "relay" {
			sourceType = "relay"
		} else if k == "chat" {
			sourceType = "chat"
		}

		matched := ""
		for _, f := range []string{"text", "source_text", "translated_text", "brse_text"} {
			if s, ok := doc[f].(string); ok && pattern.MatchString(s) {
				matched = s
				break
			}
		}
		if matched == "" {
			if tl, ok := doc["translations"].([]any); ok {
				for _, item := range tl {
					if m, ok := item.(map[string]any); ok {
						if t, ok := m["text"].(string); ok && pattern.MatchString(t) {
							matched = t
							break
						}
					}
				}
			}
		}

		snip, highlights := Snippet(matched, pattern)
		cur := EncodeCursor(strOrFallback(doc, "created_at", ""), strOrFallback(doc, "message_id", ""))
		hits = append(hits, map[string]any{
			"meeting_id":     rid,
			"meeting_title":  titles[rid],
			"source_type":    sourceType,
			"section":        nil,
			"timestamp":      doc["created_at"],
			"speaker":        doc["display_name"],
			"language":       strOrFallback(doc, "language", strOrFallback(doc, "src_lang", "")),
			"text":           snip,
			"highlights":     highlights,
			"source_item_id": doc["message_id"],
			"cursor":         cur,
		})
	}
	return hits
}

func (s *Service) Messages(
	ctx context.Context,
	access *MeetingAccess,
	kind string,
	page int,
) (map[string]any, error) {
	if page < 1 {
		page = 1
	}
	var kinds []string
	switch kind {
	case "relay":
		kinds = []string{"relay"}
	case "chat":
		kinds = []string{"chat"}
	default:
		kinds = []string{"source", "translated"}
	}

	query := bson.M{
		"room_id": access.RoomID,
		"kind":    bson.M{"$in": kinds},
	}
	total, err := s.db.Collection(MessagesCol).CountDocuments(ctx, query)
	if err != nil {
		return nil, err
	}

	cur, err := s.db.Collection(MessagesCol).Find(
		ctx,
		query,
		options.Find().
			SetSort(bson.D{{Key: "created_at", Value: 1}, {Key: "message_id", Value: 1}}).
			SetSkip(int64((page-1)*200)).
			SetLimit(200),
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
	for _, doc := range docs {
		speakerName := strOrFallback(doc, "speaker_display_name", strOrFallback(doc, "display_name", ""))
		items = append(items, map[string]any{
			"message_id":      doc["message_id"],
			"kind":            doc["kind"],
			"created_at":      doc["created_at"],
			"speaker_name":    speakerName,
			"language":        strOrFallback(doc, "language", strOrFallback(doc, "src_lang", "")),
			"target_language": doc["target_lang"],
			"text":            doc["text"],
			"source_text":     doc["source_text"],
			"translated_text": doc["translated_text"],
			"translations":    doc["translations"],
		})
	}

	return map[string]any{
		"items":     items,
		"total":     total,
		"page":      page,
		"page_size": 200,
	}, nil
}

func strOrFallback(m map[string]any, key, fallback string) string {
	if m == nil {
		return fallback
	}
	if s, ok := m[key].(string); ok && s != "" {
		return s
	}
	return fallback
}

func sanitizeMongoDoc(doc map[string]any) map[string]any {
	if doc == nil {
		return nil
	}
	clean := make(map[string]any)
	for k, v := range doc {
		if k == "_id" || strings.HasSuffix(k, "_dt") {
			continue
		}
		clean[k] = v
	}
	return clean
}
