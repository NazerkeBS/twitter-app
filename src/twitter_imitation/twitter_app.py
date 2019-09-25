import datetime
import json
import os
import time

from botocore.exceptions import ClientError
from flask import Flask, redirect, request, url_for, session, render_template
from flask_login import LoginManager
from oauthlib.oauth2 import WebApplicationClient
import requests
import redis
import boto3
import logging
from botocore.client import Config
from werkzeug.utils import secure_filename

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
app = Flask(__name__)
if os.environ.get("APP_SECRET_KEY", None):
    app.secret_key = os.environ["APP_SECRET_KEY"]
else:
    app.secret_key = ""

login_manager = LoginManager()
login_manager.init_app(app)

r = redis.StrictRedis(
    host=os.environ["REDIS_HOST"], port=6379, password="", decode_responses=True
)

if (
    os.environ.get("ENDPOINT_URL", None)
    and os.environ.get("AWS_ACCESS_KEY_ID", None)
    and os.environ.get("AWS_SECRET_ACCESS_KEY", None)
):
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["ENDPOINT_URL"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
    )
else:
    s3 = boto3.client("s3")

ALLOWED_EXTENSIONS = ["png", "jpg", "gif", "PNG", "JPG", "GIF"]

# OAuth2 client setup
client = WebApplicationClient(os.environ["GOOGLE_CLIENT_ID"])


# app entry point
@app.route("/")
def index():
    if session.get("username", None) and session.get("name", None):
        # temp_name is used for redis key
        temp_name = session["username"] + "a"
        # temp_following is for user's following list in redis
        temp_following = session["username"] + "following"
        list_all = r.lrange(temp_name, 0, -1)
        all_tweets = []
        for item in list_all:
            unpack = json.loads(item)
            all_tweets.append(unpack)
        following_users = r.lrange(temp_following, 0, -1)
        for user in following_users:
            unpacked = json.loads(user)
            id_name = unpacked[0] + "a"
            tweets = r.lrange(id_name, 0, -1)
            for tweet_tuple in tweets:
                unpack_tuple = json.loads(tweet_tuple)
                all_tweets.append(unpack_tuple)
        all_tweets.sort(key=lambda x: x[0], reverse=True)
        return render_template("home.html", name=session["name"], tweets=all_tweets)
    else:
        error = None
        return render_template("index.html", error=error)


# login
@app.route("/login")
def login():
    google_provider_cfg = get_google_provider_cfg()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]

    request_uri = client.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=request.base_url + "/callback",
        scope=["openid", "email", "profile"],
    )
    return redirect(request_uri)


# login using Google OpenID Connect
@app.route("/login/callback")
def callback():
    code = request.args.get("code")

    google_provider_cfg = get_google_provider_cfg()
    token_endpoint = google_provider_cfg["token_endpoint"]

    token_url, headers, body = client.prepare_token_request(
        token_endpoint,
        authorization_response=request.url,
        redirect_url=request.base_url,
        code=code,
    )
    token_response = requests.post(
        token_url,
        headers=headers,
        data=body,
        auth=(os.environ["GOOGLE_CLIENT_ID"], os.environ["GOOGLE_CLIENT_SECRET"]),
    )

    client.parse_request_body_response(json.dumps(token_response.json()))

    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    uri, headers, body = client.add_token(userinfo_endpoint)
    userinfo_response = requests.get(uri, headers=headers, data=body)

    if userinfo_response.json().get("email_verified"):
        response_json = userinfo_response.json()
        unique_id = response_json.get("sub", None)
        users_email = response_json.get("email", None)
        users_name = response_json.get("given_name", None)
        full_name = response_json.get("name", None)
        profile_image = response_json.get("picture", None)
        session["username"] = unique_id
        if users_name:
            session["name"] = users_name
        if full_name:
            session["full_name"] = full_name
        if users_email:
            session["email"] = users_email
        if profile_image:
            session["profile_image"] = profile_image
        user_tuple = (unique_id, full_name, "follow")
        temp_name_all_users = session["username"] + "all_users"
        packed = json.dumps(user_tuple)
        temp_ = "all_users"
        if not exists_user(session["username"], temp_):
            r.lpush("all_users", packed)
        all_users = r.lrange("all_users", 0, -1)
        for user in all_users:
            unpack = json.loads(user)
            if not exists_user(unpack[0], temp_name_all_users):
                pack = json.dumps(unpack)
                r.lpush(temp_name_all_users, pack)
        print(r.lrange(temp_name_all_users, 0, -1))

    else:
        return "User email not available or not verified by Google.", 400
    return redirect(url_for("index"))


# post a new tweet
@app.route("/tweet", methods=["POST"])
def post_tweet():
    if session.get("username", None):
        temp_following = session["username"] + "following"
        img_file = request.files.get("img_file", None)
        tweet = request.form["tweet"]
        link_image = None
        if (
            img_file
            and allowed_file(img_file.filename)
            and "image" in img_file.mimetype
        ):
            filename = secure_filename(img_file.filename)
            img_file.save(filename)
            put_image(filename, session["username"])
            os.remove(filename)
            try:
                link_image = s3.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": "intern-naz",
                        "Key": session["username"] + "a" + "/" + filename,
                    },
                    HttpMethod="GET",
                    ExpiresIn=7200,
                )
            except ClientError as e:
                logging.error(e)
            print(link_image)
        if tweet:
            t = time.time()
            timeline = datetime.datetime.fromtimestamp(t).strftime("%c")
            tup = timeline, tweet, session["name"]
            if link_image is not None:
                tup = timeline, tweet, session["name"], link_image
            s = json.dumps(tup)
            temp_name = session["username"] + "a"
            r.lpush(temp_name, s)
        return render_template(
            "home.html",
            name=session["name"],
            tweets=load_all_tweets(temp_name, temp_following),
        )
    else:
        return redirect(url_for("index"))


# delete existing tweet
@app.route("/tweet", methods=["DELETE"])
def delete_tweet():
    if session.get("username", None):
        temp_name = session["username"] + "a"
        temp_following = session["username"] + "following"
        list_all = r.lrange(temp_name, 0, -1)
        deleted_data = request.form["tweet"].rstrip().strip("\n").splitlines()
        for item in list_all:
            unpack = json.loads(item)
            for deleted in deleted_data:
                deleted_ = deleted.strip(" ")
                if deleted_ == unpack[0]:
                    r.lrem(temp_name, 1, json.dumps(unpack))
        return render_template(
            "home.html",
            name=session["name"],
            tweets=load_all_tweets(temp_name, temp_following),
        )
    else:
        return redirect(url_for("index"))


# edit existing tweet
@app.route("/tweet", methods=["PUT"])
def edit_tweet():
    if session.get("username", None):
        temp_name = session["username"] + "a"
        temp_following = session["username"] + "following"
        list_all = r.lrange(temp_name, 0, -1)
        updated_data = request.form["tweet"].rstrip().lstrip()
        timestamp = request.form["timestamp"].rstrip()
        for item in list_all:
            unpack = json.loads(item)
            if unpack[0].replace(" ", "") == timestamp.replace(" ", ""):
                prev = unpack
                r.lrem(temp_name, 1, json.dumps(prev))
                unpack[1] = updated_data
                tup = (unpack[0], unpack[1], unpack[2])
                try:
                    if unpack[3]:
                        tup = (unpack[0], unpack[1], unpack[2], unpack[3])
                except IndexError:
                    pass
                packed = json.dumps(tup)
                r.lpush(temp_name, packed)
        return render_template(
            "home.html",
            name=session["name"],
            tweets=load_all_tweets(temp_name, temp_following),
        )
    else:
        return redirect(url_for("index"))


# get all users
@app.route("/users", methods=["GET"])
def users():
    if session.get("username", None):
        all_users = []
        all_tweets = []
        temp_following = session["username"] + "following"
        temp_name = session["username"] + "a"
        list_all_tweets = r.lrange(temp_name, 0, -1)
        temp_name_all_users = session["username"] + "all_users"
        list_all = r.lrange(temp_name_all_users, 0, -1)
        for item in list_all:
            unpacked = json.loads(item)
            if unpacked[0] != session["username"]:
                tup = unpacked[1], unpacked[2]
                all_users.append(tup)
        for item_tweet in list_all_tweets:
            unpack = json.loads(item_tweet)
            all_tweets.append(unpack)
        following_users = r.lrange(temp_following, 0, -1)
        for user in following_users:
            unpacked = json.loads(user)
            id_name = unpacked[0] + "a"
            tweets = r.lrange(id_name, 0, -1)
            for tweet_tuple in tweets:
                unpack_tuple = json.loads(tweet_tuple)
                all_tweets.append(unpack_tuple)
        all_tweets.sort(key=lambda x: x[0], reverse=True)
        return render_template(
            "home.html", name=session["name"], all_users=all_users, tweets=all_tweets
        )
    else:
        return redirect(url_for("index"))


# following users
@app.route("/users/following")
def following():
    if session.get("username", None):
        all_users = []
        all_tweets = []
        temp_following = session["username"] + "following"
        temp_name = session["username"] + "a"
        following_users = r.lrange(temp_following, 0, -1)
        list_all_tweets = r.lrange(temp_name, 0, -1)
        for item_tweet in list_all_tweets:
            unpack = json.loads(item_tweet)
            all_tweets.append(unpack)
        for user in following_users:
            unpack = json.loads(user)
            tup = unpack[1], unpack[2]
            all_users.append(tup)
            id_name = unpack[0] + "a"
            tweets = r.lrange(id_name, 0, -1)
            for tweet_tuple in tweets:
                unpack_tuple = json.loads(tweet_tuple)
                all_tweets.append(unpack_tuple)
        all_tweets.sort(key=lambda x: x[0], reverse=True)
        return render_template(
            "home.html", name=session["name"], all_users=all_users, tweets=all_tweets
        )
    else:
        return redirect(url_for("index"))


# follow user
@app.route("/users/follow", methods=["POST"])
def follow():
    all_users = []
    temp_name = session["username"] + "following"
    user_to_follow = request.form["data"]
    temp_name_all_users = session["username"] + "all_users"
    list_all = r.lrange(temp_name_all_users, 0, -1)
    for item in list_all:
        unpacked = json.loads(item)
        if unpacked[1] == user_to_follow:
            temp = unpacked
            temp_packed = json.dumps(temp)
            r.lrem(temp_name_all_users, 1, temp_packed)
            unpacked[2] = "unfollow"
            packed = json.dumps(unpacked)
            r.lpush(temp_name_all_users, packed)
            r.lpush(temp_name, packed)
    list_all = r.lrange(temp_name_all_users, 0, -1)
    for item in list_all:
        unpack = json.loads(item)
        all_users.append(unpack)
    return render_template("home.html", name=session["name"], tweets=all_users)


# unfollow user
@app.route("/users/unfollow", methods=["POST"])
def unfollow():
    all_users = []
    temp_name = session["username"] + "following"
    user_to_unfollow = request.form["data"]
    temp_name_all_users = session["username"] + "all_users"
    list_all = r.lrange(temp_name_all_users, 0, -1)
    for item in list_all:
        unpacked = json.loads(item)
        if unpacked[1] == user_to_unfollow:
            temp = unpacked
            temp_packed = json.dumps(temp)
            r.lrem(temp_name_all_users, 1, temp_packed)
            r.lrem(temp_name, 1, temp_packed)
            unpacked[2] = "follow"
            packed = json.dumps(unpacked)
            r.lpush(temp_name_all_users, packed)
    list_all = r.lrange(temp_name_all_users, 0, -1)
    for item in list_all:
        unpack = json.loads(item)
        all_users.append(unpack)
    return render_template("home.html", name=session["name"], tweets=all_users)


# logout
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# user profile
@app.route("/profile")
def profile():
    if session.get("username", None):
        error = None
        return render_template(
            "profile.html",
            error=error,
            name=session["full_name"],
            profile_image=session["profile_image"],
            email=session["email"],
        )
    else:
        return redirect(url_for("index"))


def load_all_tweets(temp_name, temp_following):
    all_tweets = []
    list_all = r.lrange(temp_name, 0, -1)
    for item in list_all:
        unpack = json.loads(item)
        all_tweets.append(unpack)
    following_users = r.lrange(temp_following, 0, -1)
    for user in following_users:
        unpacked = json.loads(user)
        id_name = unpacked[0] + "a"
        tweets = r.lrange(id_name, 0, -1)
        for tweet_tuple in tweets:
            unpack_tuple = json.loads(tweet_tuple)
            all_tweets.append(unpack_tuple)
    all_tweets.sort(key=lambda x: x[0], reverse=True)
    return all_tweets


def get_google_provider_cfg():
    return requests.get(GOOGLE_DISCOVERY_URL).json()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1] in ALLOWED_EXTENSIONS


# upload image file to s3
def put_image(filename, username):
    username = username + "a"
    key = username + "/" + filename
    try:
        s3.head_bucket(Bucket="intern-naz")
    except ClientError:
        s3.create_bucket(Bucket="intern-naz")
    with open(filename, "rb") as picture:
        s3.put_object(Body=picture, Bucket="intern-naz", Key=key)


def exists_user(current_user_id, temp_name):
    list_all_users = r.lrange(temp_name, 0, -1)
    if len(list_all_users) == 0:
        return False
    for item in list_all_users:
        unpacked = json.loads(item)
        if unpacked[0] == current_user_id:
            return True
    return False


def main():
    app.run(host="0.0.0.0", port=5000)


if __name__ == "__main__":
    app.jinja_env.auto_reload = True
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    main()
