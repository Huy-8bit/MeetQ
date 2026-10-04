# Writer: scheduled/manual backups (+ list/read for verify and pre-restore checks).
data "aws_iam_policy_document" "writer" {
  statement {
    sid       = "ListBackups"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.backups.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = [for env in var.environments : "${local.prefix}/${env}/*"]
    }
  }

  statement {
    sid = "WriteBackups"
    actions = concat(
      ["s3:PutObject", "s3:PutObjectTagging", "s3:GetObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
      var.allow_prune ? ["s3:DeleteObject"] : [],
    )
    resources = [for env in var.environments : "${aws_s3_bucket.backups.arn}/${local.prefix}/${env}/*"]
  }
}

# Reader: list/download/restore only (no write, no delete).
data "aws_iam_policy_document" "reader" {
  statement {
    sid       = "ListBackups"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.backups.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = [for env in var.environments : "${local.prefix}/${env}/*"]
    }
  }

  statement {
    sid       = "ReadBackups"
    actions   = ["s3:GetObject"]
    resources = [for env in var.environments : "${aws_s3_bucket.backups.arn}/${local.prefix}/${env}/*"]
  }
}

resource "aws_iam_policy" "writer" {
  name   = "${var.project_name}-db-backup-writer"
  policy = data.aws_iam_policy_document.writer.json
}

resource "aws_iam_policy" "reader" {
  name   = "${var.project_name}-db-backup-reader"
  policy = data.aws_iam_policy_document.reader.json
}

resource "aws_iam_user" "writer" {
  count = var.create_iam_users ? 1 : 0
  name  = "${var.project_name}-db-backup-writer"
  path  = "/meetq/"
}

resource "aws_iam_user_policy_attachment" "writer" {
  count      = var.create_iam_users ? 1 : 0
  user       = aws_iam_user.writer[0].name
  policy_arn = aws_iam_policy.writer.arn
}

resource "aws_iam_user" "reader" {
  count = var.create_iam_users ? 1 : 0
  name  = "${var.project_name}-db-backup-reader"
  path  = "/meetq/"
}

resource "aws_iam_user_policy_attachment" "reader" {
  count      = var.create_iam_users ? 1 : 0
  user       = aws_iam_user.reader[0].name
  policy_arn = aws_iam_policy.reader.arn
}

resource "aws_iam_role_policy_attachment" "writer" {
  for_each   = toset(var.writer_role_names)
  role       = each.value
  policy_arn = aws_iam_policy.writer.arn
}
