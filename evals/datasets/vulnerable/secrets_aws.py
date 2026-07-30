import boto3

AWS_ACCESS_KEY = "AKIAQ7Z9W2X5V8B1N4M6"
AWS_SECRET_KEY = "zR8kLmN3pQ7sT2vW5xY9aB4cD6eF1gH3jK5lM7nP"

client = boto3.client("s3", aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY)
