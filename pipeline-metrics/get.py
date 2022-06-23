#!/usr/bin/env python3

import json
import requests
import os
import sys
import boto3
import glob
from datetime import datetime

DATE_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

org = sys.argv[1]
name = sys.argv[2]
aws_access_key_id = sys.argv[3]
aws_secret_access_key = sys.argv[4]
aws_s3_bucket = sys.argv[5]
github_token = sys.argv[6]

# s3 object to get/push json files
session = boto3.Session(
    aws_access_key_id = aws_access_key_id,
    aws_secret_access_key = aws_secret_access_key,
)
s3 = session.resource('s3')

url = f"https://api.github.com/repos/{org}/{name}/actions/runs"
headers = {"Accept":"application/vnd.github.v3+json", "Authorization":f"token {github_token}"}

# Get actions runs 
r = requests.get(url=url, headers=headers)
workflow_runs_data = r.json()

# print(workflow_runs_data)
if workflow_runs_data["total_count"] == 0:
    raise Exception(f"Missing workflow for {org}/{name}")
latest_run_id = workflow_runs_data["workflow_runs"][0]["id"]

# Get latest run info
r = requests.get(url=f"{url}/{latest_run_id}", headers=headers)
latest_run_data = r.json()

# Initialize resulting object
triggered_by = None
if 'triggering_actor' in latest_run_data:
  triggered_by = f"{latest_run_data['triggering_actor']['login']}"

latest_job_info = {
    "name": name,
    "full_name": f"{latest_run_data['name']}",
    "date": f"{latest_run_data['created_at']}",
    "pipeline_url": f"{latest_run_data['html_url']}",
    "triggered_by": triggered_by,
    "commit_url": f"https://github.com/{org}/{name}/commit/{latest_run_data['head_commit']['id']}",
}

# Get latest run jobs info
r = requests.get(url=f"{url}/{latest_run_id}/jobs", headers=headers)
latest_run_jobs_data = r.json()

# Get ci job status
latest_job_info["status"] = latest_run_jobs_data["jobs"][0]["conclusion"]

# Calculate job duration
started_at=datetime.strptime(latest_run_jobs_data["jobs"][0]["started_at"], DATE_TIME_FORMAT)
completed_at=datetime.strptime(latest_run_jobs_data["jobs"][0]["completed_at"], DATE_TIME_FORMAT)
td = completed_at - started_at
latest_job_info["duration"] = int(td.total_seconds())

# Get status of job steps
latest_job_info["builded"] = None
latest_job_info["tested"] = None
latest_job_info["published"] = None
latest_job_info["released"] = None
steps_duration = []

for step in latest_run_jobs_data["jobs"][0]["steps"]:
    if step["name"].split(" ")[0].lower() == "build":
        if step["conclusion"] == "success":
            latest_job_info["builded"] = True
        else:
            latest_job_info["builded"] = False
    elif step["name"].split(" ")[0].lower() == "test":
        if step["conclusion"] == "success":
            latest_job_info["tested"] = True
        else:
            latest_job_info["tested"] = False
    elif step["name"].split(" ")[0].lower() == "publish":
        if step["conclusion"] == "success":
            latest_job_info["published"] = True
        else:
            latest_job_info["published"] = False
    elif step["name"].split(" ")[0].lower() == "release":
        if step["conclusion"] == "success":
            latest_job_info["released"] = True
        else:
            latest_job_info["released"] = False
    
    # Get step duration
    started_at=datetime.strptime(f'{step["started_at"].split(".")[0]}Z', DATE_TIME_FORMAT)
    completed_at=datetime.strptime(f'{step["completed_at"].split(".")[0]}Z', DATE_TIME_FORMAT)
    td = completed_at - started_at
    duration = int(td.total_seconds())
    steps_duration.append({
        "name": step["name"],
        "duration": duration
    })

# Read pipelines info file
s3_objects = s3.meta.client.list_objects(Bucket=aws_s3_bucket)
for s3_file in s3_objects["Contents"]:
    if s3_file["Key"] == f"{org}_latest_full.json":
        s3.meta.client.download_file(Bucket=aws_s3_bucket, Key=f"{org}_latest_full.json", Filename=f"{org}_latest_full.json")

if os.path.exists(f"{org}_latest_full.json"):
    with open(f"{org}_latest_full.json", "r") as f:
        latest_pipelines = json.loads(f.read())

    new_pipeline = True
    new_latest_pipelines = []
    for pipeline in latest_pipelines:
        if pipeline["name"] == latest_job_info["name"]:
            new_latest_pipelines.append(latest_job_info)
            new_pipeline = False
        else:
            new_latest_pipelines.append(pipeline)
    if new_pipeline:
        new_latest_pipelines.append(latest_job_info)
else:
    new_latest_pipelines = []
    new_latest_pipelines.append(latest_job_info)

# Calculate status of pipelines in group
now = datetime.utcnow()
now_formated = now.strftime(DATE_TIME_FORMAT)
pipelines_group_status = {
    "date": now_formated,
    "total": 0,
    "success": 0,
    "failed": 0,
    "builded": 0,
    "tested": 0,
    "published": 0,
    "released": 0
}
for pipeline in new_latest_pipelines:
    pipelines_group_status["total"] += 1
    if pipeline["status"] == "success":
        pipelines_group_status["success"] += 1
    else:
        pipelines_group_status["failed"] += 1
    if pipeline.get("builded") is not None:
        if pipeline["builded"]:
            pipelines_group_status["builded"] += 1
    if pipeline.get("tested") is not None:
        if pipeline["tested"]:
            pipelines_group_status["tested"] += 1
    if pipeline.get("published") is not None:
        if pipeline["published"]:
            pipelines_group_status["published"] += 1
    if pipeline.get("released") is not None:
        if pipeline["released"]:
            pipelines_group_status["released"] += 1

# Calculate status of all repo groups in bucket
# Download all status files from bucket
if "Contents" in s3_objects:
    for s3_file in s3_objects["Contents"]:
        if "_status.json" in s3_file["Key"]:
            s3.meta.client.download_file(Bucket=aws_s3_bucket, Key=s3_file["Key"], Filename=s3_file["Key"])

total_status = {
    "date": now_formated,
    "total": 0,
    "success": 0,
    "failed": 0,
    "builded": 0,
    "tested": 0,
    "published": 0,
    "released": 0
}
status_files = glob.glob("*_status.json")
for status_file in status_files:
    print(f"reading {status_file}")
    with open(status_file, "r") as f:
        status = json.loads(f.read())
    total_status["total"] += status["total"]
    total_status["success"] += status["success"]
    total_status["failed"] += status["failed"]
    total_status["builded"] += status["builded"]
    total_status["tested"] += status["tested"]
    total_status["published"] += status["published"]
    total_status["released"] += status["released"]

# Save results to files
with open(f"{org}_latest_full.json", "w") as f:
    json.dump(new_latest_pipelines, f)
with open(f"{org}_status.json", "w") as f:
    json.dump(pipelines_group_status, f)
with open("total_status.json", "w") as f:
    json.dump(total_status, f)
with open(f"{name}_duration.json", "w") as f:
    json.dump(steps_duration, f)

# Upload to s3
s3.meta.client.upload_file(Filename=f"{org}_latest_full.json", Bucket=aws_s3_bucket, Key=f"{org}_latest_full.json")
s3.meta.client.upload_file(Filename=f"{org}_status.json", Bucket=aws_s3_bucket, Key=f"{org}_status.json")
s3.meta.client.upload_file(Filename="total_status.json", Bucket=aws_s3_bucket, Key="total_status.json")
s3.meta.client.upload_file(Filename=f"{name}_duration.json", Bucket=aws_s3_bucket, Key=f"durations/{name}_duration.json")

print("****************************************\n***  pipeline metrics uploaded to s3 ***\n****************************************")
