import boto3
import botocore

s3 = boto3.client("s3")

# list buckets in s3
response = s3.list_buckets()
buckets = [bucket["Name"] for bucket in response["Buckets"]]
print("Bucket List: %s" % buckets)

# upload a file to s3
""" 
filename='in.txt'
bucket_name = 'intern-naz'
s3.file_upload(filename, bucket_name, filename)
"""

# download a file from s3
BUCKET_NAME = "intern-naz"
KEY = "in.txt"
s3 = boto3.resource("s3")

try:
    s3.Bucket(BUCKET_NAME).download_file(KEY)
except botocore.exceptions.ClientError as e:
    if e.response["Error"]["Code"] == "404":
        print("The file does not exist.")
    else:
        raise
