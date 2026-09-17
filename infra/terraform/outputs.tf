output "cluster_name" { value = module.eks.cluster_name }
output "ecr_repositories" { value = { for k, v in aws_ecr_repository.images : k => v.repository_url } }
output "postgres_endpoint" { value = aws_db_instance.postgres.address }
output "postgres_username" { value = aws_db_instance.postgres.username }
output "postgres_database" { value = aws_db_instance.postgres.db_name }
output "postgres_password" { value = random_password.db.result, sensitive = true }
