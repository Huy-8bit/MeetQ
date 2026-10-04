"""Meeting recording, meeting archive and retention (docs/meeting-recording-and-retention.md).

Live meeting data stays in Redis/MongoDB. When a meeting ends, the archive worker
writes a JSON snapshot plus manifest to the private S3 bucket; recordings are written
there directly by LiveKit Egress. `meeting_archives.expires_at` drives deletion.
"""
