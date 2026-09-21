provider "aws" { region = var.aws_region }

data "aws_availability_zones" "available" { state = "available" }

module "vpc" {
  source                       = "terraform-aws-modules/vpc/aws"
  version                      = ">= 5.0, < 7.0"
  name                         = "opspilot"
  cidr                         = "10.42.0.0/16"
  azs                          = slice(data.aws_availability_zones.available.names, 0, 2)
  private_subnets              = ["10.42.1.0/24", "10.42.2.0/24"]
  public_subnets               = ["10.42.101.0/24", "10.42.102.0/24"]
  database_subnets             = ["10.42.11.0/24", "10.42.12.0/24"]
  create_database_subnet_group = true
  enable_nat_gateway           = true
  single_nat_gateway           = true
}

module "eks" {
  source                                   = "terraform-aws-modules/eks/aws"
  version                                  = ">= 21.0, < 22.0"
  name                                     = "opspilot"
  kubernetes_version                       = var.kubernetes_version
  vpc_id                                   = module.vpc.vpc_id
  subnet_ids                               = module.vpc.private_subnets
  enable_cluster_creator_admin_permissions = true
  eks_managed_node_groups = {
    default = {
      instance_types = ["t3.large"]
      min_size       = 2
      max_size       = 4
      desired_size   = 2
    }
  }
}

resource "aws_ecr_repository" "images" {
  for_each = toset(["catalog", "payment", "checkout", "agent", "dashboard"])
  name     = "opspilot/${each.key}"
  image_scanning_configuration { scan_on_push = true }
}

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "aws_security_group" "postgres" {
  name   = "opspilot-postgres"
  vpc_id = module.vpc.vpc_id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "postgres" {
  identifier              = "opspilot"
  engine                  = "postgres"
  engine_version          = var.postgres_version
  instance_class          = "db.t4g.micro"
  allocated_storage       = 20
  max_allocated_storage   = 100
  db_name                 = "opspilot"
  username                = "opspilot"
  password                = random_password.db.result
  db_subnet_group_name    = module.vpc.database_subnet_group_name
  vpc_security_group_ids  = [aws_security_group.postgres.id]
  publicly_accessible     = false
  storage_encrypted       = true
  backup_retention_period = 1
  skip_final_snapshot     = true
  deletion_protection     = false
}
