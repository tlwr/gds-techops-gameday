from locust import HttpLocust, TaskSet, task, runners
import boto3
from datetime import datetime
import hashlib
import re
import names
import os
import math


class WebsiteTasks(TaskSet):
    team = os.environ.get("TEAM", "one")
    difficulty = int(os.environ.get("APP_DIFFICULTY", 17))
    points = int(os.environ.get("POINTS", 1))
    scale_up = int(os.environ.get("SWARM_SCALE_UP", 5))
    scale_down = int(os.environ.get("SWARM_SCALE_DOWN", 1))
    timeout = int(os.environ.get("TIMEOUT", 8))

    def setup(self):
        r = runners.locust_runner
        if "failures" not in dir(r):
            r.failures = 0
            r.success = 0
            r.backoff = 0

    @task(1)
    def register(self):
        r = runners.locust_runner
        now = str(datetime.now().timestamp())
        name = {
            "first_name": f"{names.get_first_name()}_{now.split('.')[0]}",
            "last_name": f"{names.get_last_name()}_{now.split('.')[1]}",
        }
        with self.client.post("/register", name, catch_response=True) as response:
            try:
                assert response.elapsed.seconds < self.timeout, "Too slow!"
                assert (
                    response.status_code == 200
                ), f"FAILED! status_code: {response.status_code}"
                self.valid_receipt(response, name)
                self.send_points(1)
                r.success += 1
            except AssertionError as e:
                print(e, end="")
                response.failure(e)
                r.failures += 1
            self.scale()

    @task(120)
    def index(self):
        r = runners.locust_runner

        with self.client.get("/", catch_response=True) as response:
            try:
                assert response.status_code == 200

            except AssertionError as e:
                r.failures += 1
                self.scale()

    @task(30)
    def stats(self):
        r = runners.locust_runner

        with self.client.get("/stats", catch_response=True) as response:
            try:
                assert response.status_code == 200
            except AssertionError as e:
                r.failures += 1
                self.scale()

    def scale(self):
        r = runners.locust_runner
        print(
            f"Failed: {r.failures}  Successful: {r.success}, locusts:{r.num_clients}, backoff:{r.backoff}"
        )

        if r.success >= self.scale_up:
            r.start_hatching(r.num_clients + 1)
            r.success = 0
            print(f"A locust joins the swarm: {r.user_count + 1} locusts")

        elif r.failures >= self.scale_down:
            if r.num_clients > 1:
                self.send_points(-r.user_count)
                r.backoff += 10

                kill = math.ceil(r.user_count / 100.0 * r.backoff)
                r.start_hatching(max(r.user_count - kill, 1))

                print(f"A locust dies: {r.user_count - 1} locusts")

                if r.user_count == 1:
                    r.backoff -= 1
            r.failures = 0

    def valid_receipt(self, response, name):
        sha2 = re.search(r"([0-9a-fA-F]{64})", response.text)
        code = re.search(r"x(\d+)x", response.text)

        h = hashlib.sha256()
        v = f"{name['first_name']}{name['last_name']}{code[1]}".encode("utf-8")
        h.update(v)

        assert sha2[0] == h.hexdigest(), f"FAILED! Hashes don't match"

        h = "".join(format(n, "08b") for n in h.digest())

        assert (
            h[: self.difficulty] == "0" * self.difficulty
        ), f"FAILED! Incorrect difficulty!"

        return True

    def send_points(self, points):
        dynamodb = boto3.resource("dynamodb", region_name="eu-west-2")
        table_name = "gameday_team_points"
        table = dynamodb.Table(table_name)
        item = {
            "team": self.team,
            "source": "locust",
            "points": points,
            "datetime": str(datetime.now()),
        }
        table.put_item(Item=item)


class WebsiteUser(HttpLocust):
    task_set = WebsiteTasks
    min_wait = 100
    max_wait = 400
    timeout = 30