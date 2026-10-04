output "bucket_name" {
  description = "DB_BACKUP_S3_BUCKET"
  value       = aws_s3_bucket.backups.bucket
}

output "backup_prefix" {
  description = "DB_BACKUP_S3_PREFIX"
  value       = local.prefix
}

output "aws_region" {
  value = var.aws_region
}

output "writer_user" {
  description = "aws iam create-access-key --user-name <this>  (backup hosts)"
  value       = var.create_iam_users ? aws_iam_user.writer[0].name : null
}

output "reader_user" {
  description = "aws iam create-access-key --user-name <this>  (restore-only laptops)"
  value       = var.create_iam_users ? aws_iam_user.reader[0].name : null
}

output "writer_policy_arn" {
  value = aws_iam_policy.writer.arn
}

output "reader_policy_arn" {
  value = aws_iam_policy.reader.arn
}
