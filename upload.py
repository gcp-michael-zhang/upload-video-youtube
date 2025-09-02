#!/usr/bin/python3

import httplib2
import os
import random
import sys
import time

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from oauth2client.tools import argparser, run_flow

# The CLIENT_SECRETS_FILE variable specifies the name of a file that contains
# the OAuth 2.0 information for this application, including its client_id and
# client_secret.
CLIENT_SECRETS_FILE = "client_secrets.json"

# This OAuth 2.0 access scope allows an application to upload files to the
# authenticated user's YouTube channel.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

# This variable defines a message to display if the CLIENT_SECRETS_FILE is missing.
MISSING_CLIENT_SECRETS_MESSAGE = """
WARNING: Please configure OAuth 2.0

To make this sample run, you will need to populate the client_secrets.json file
found at:

   %s

with information from the API Console
https://console.cloud.google.com/

For more information about the client_secrets.json file format, please visit:
https://developers.google.com/api-client-library/python/guide/aaa_client_secrets
""" % os.path.abspath(os.path.join(os.path.dirname(__file__), CLIENT_SECRETS_FILE))

# Maximum number of times to retry before giving up.
MAX_RETRIES = 10

# Always retry when these exceptions are raised.
RETRIABLE_EXCEPTIONS = (httplib2.HttpLib2Error, IOError)

# Always retry when an apiclient.errors.HttpError with one of these status
# codes is raised.
RETRIABLE_STATUS_CODES = [500, 502, 503, 504]


def get_authenticated_service():
    """Authenticates the user and returns the YouTube API service."""
    creds = None
    # The file token.json stores the user's access and refresh tokens.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRETS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build(API_SERVICE_NAME, API_VERSION, credentials=creds)

def initialize_upload(youtube, options):
    """Initializes a resumable upload to YouTube."""
    tags = None
    if options.keywords:
        tags = options.keywords.split(",")

    body = dict(
        snippet=dict(
            title=options.title,
            description=options.description,
            tags=tags,
            categoryId=options.category,
        ),
        status=dict(privacyStatus=options.privacyStatus),
    )

    insert_request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=MediaFileUpload(
            options.file, chunksize=-1, resumable=True
        ),
    )

    resumable_upload(insert_request)


def resumable_upload(insert_request):
    """This method implements an exponential backoff strategy to resume a failed upload."""
    response = None
    error = None
    retry = 0
    while response is None:
        try:
            print("Uploading file...")
            status, response = insert_request.next_chunk()
            if status:
                print(f"Uploaded {int(status.progress() * 100)}%")
            if response is not None:
                if "id" in response:
                    video_url = f"https://www.youtube.com/watch?v={response['id']}"
                    print(f" -> Uploaded video ID {response['id']} - {video_url}")
                else:
                    exit(f"The upload failed with an unexpected response: {response}")
        except HttpError as e:
            if e.resp.status in RETRIABLE_STATUS_CODES:
                error = f"A retriable HTTP error {e.resp.status} occurred:\n{e.content}"
            else:
                raise
        except RETRIABLE_EXCEPTIONS as e:
            error = f"A retriable error occurred: {e}"

        if error is not None:
            print(error)
            retry += 1
            if retry > MAX_RETRIES:
                exit("No longer attempting to retry.")

            max_sleep = 2**retry
            sleep_seconds = random.random() * max_sleep
            print(f"Sleeping {sleep_seconds:.2f} seconds and then retrying...")
            time.sleep(sleep_seconds)


if __name__ == "__main__":
    from argparse import ArgumentParser

    parser = ArgumentParser(description="Uploads a video to YouTube.")
    parser.add_argument("--file", required=True, help="Video file to upload")
    parser.add_argument("--title", help="Video title", default="Test Title")
    parser.add_argument("--description", help="Video description", default="Test Description")
    parser.add_argument(
        "--category",
        default="22",
        help="Numeric video category. See https://developers.google.com/youtube/v3/docs/videoCategories/list",
    )
    parser.add_argument(
        "--keywords", help="Video keywords, comma separated", default=""
    )
    VALID_PRIVACY_STATUSES = ("public", "private", "unlisted")
    parser.add_argument(
        "--privacyStatus",
        choices=VALID_PRIVACY_STATUSES,
        default=VALID_PRIVACY_STATUSES[0],
        help="Video privacy status.",
    )
    args = parser.parse_args()

    if not os.path.exists(args.file):
        exit(f"Please specify a valid file using the --file= parameter.")

    youtube_service = get_authenticated_service()
    try:
        initialize_upload(youtube_service, args)
    except HttpError as e:
        print(f"An HTTP error {e.resp.status} occurred:\n{e.content}")