import json

import pytest
import redis

from twitter_imitation import twitter_app


@pytest.fixture
def app(redis_connector):
    app = twitter_app.app
    app.config["DEBUG"] = True
    app.config["TESTING"] = True
    return app


@pytest.fixture
def redis_connector(monkeypatch):
    r = redis.StrictRedis(
        db=1,
        host=twitter_app.redis_host,
        port=twitter_app.redis_port,
        password=twitter_app.redis_password,
        decode_responses=True,
    )
    monkeypatch.setattr(twitter_app, "r", r)
    yield r
    r.flushdb()


def test_main_page(client):
    response = client.get("/")
    assert response.status_code == 200


def test_empty_db():
    tweets = twitter_app.r.lrange("test", 0, -1)
    assert [] == tweets


def test_post_tweet(client):
    with client.session_transaction() as session:
        session["username"] = "test"
        session["name"] = "The Test"
    response = client.post("/tweet", data={"tweet": "hey"})
    assert response.status_code == 200
    tweets = twitter_app.r.lrange("testa", 0, -1)
    assert len(tweets) == 1


def test_delete_tweet(client):
    with client.session_transaction() as session:
        session["username"] = "test"
        session["name"] = "The Test"
    data = {"tweet": "hey"}
    client.post("/tweet", data=data)
    tweets = twitter_app.r.lrange("testa", 0, -1)
    unpack = json.loads(tweets[0])
    response_del = client.delete("/tweet", data={"tweet": unpack[1]})
    assert response_del.status_code == 200
