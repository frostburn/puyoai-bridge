#!/usr/bin/env python
import struct
import sys
import subprocess
import json
from collections import defaultdict
from time import sleep

P1_WIN = 1
DRAW = 0
P2_WIN = -1

EMPTY = 0
OJAMA = -1
WALL = -2
IRON = -3

WIDTH = 6
HEIGHT = 12
GHOST_HEIGHT = 1

def chunks(l, n):
    return [l[i:i + n] for i in range(0, len(l), n)]

def puyo_to_int(payload):
    puyo = int(payload)
    if puyo < 4:
        return -puyo
    else:
        return puyo - 3

def puyo_from_int(puyo):
    if puyo <= 0:
        return str(-puyo)
    else:
        return str(puyo + 3)

def render_puyo(puyo):
    if puyo == EMPTY:
        return "  "
    elif puyo == OJAMA:
        return "@ "
    else:
        return str(puyo) + " "

def render_kumipuyo(kumipuyo, puyo):
    if puyo == EMPTY:
        flag = "."
    elif puyo == kumipuyo:
        flag = "*"
    else:
        flag = render_puyo(puyo)[0]
    return render_puyo(kumipuyo)[0] + flag

def field_from_string(payload):
    return list(map(puyo_to_int, payload))

def kumipuyos_from_string(payload):
    return list(map(puyo_to_int, chunk) for chunk in chunks(payload, 2))

def field_to_string(field):
    return "".join(map(puyo_from_int, field))

def kumipuyos_to_string(kumipuyos):
    result = ""
    for piece in kumipuyos:
        for puyo in piece:
            result += puyo_from_int(puyo)
    return result

class UserEvent(object):
    def __init__(self, next_appeared, grounded, pre_decision_request, decicion_request, decicion_request_again, ojama_dropped, puyo_erased):
        self.next_appeared = next_appeared
        self.grounded = grounded
        self.pre_decision_request = pre_decision_request
        self.decicion_request = decicion_request
        self.decicion_request_again = decicion_request_again
        self.ojama_dropped = ojama_dropped
        self.puyo_erased = puyo_erased

    def to_string(self):
        result = ""
        flags = [
            ("W", self.next_appeared),
            ("G", self.grounded),
            ("P", self.pre_decision_request),
            ("D", self.decicion_request),
            ("A", self.decicion_request_again),
            ("O", self.ojama_dropped),
            ("E", self.puyo_erased),
        ]
        for flag, value in flags:
            result += flag if value else "-"
        return result

    def __nonzero__(self):
        return (self.to_string() != "-------")

    @classmethod
    def from_string(cls, payload):
        args = []
        for flag in payload:
            args.append(flag != "-")
        return cls(*args)

class PlayerFrameRequest(object):
    def __init__(self, field, kumipuyos, score, kumipuyo_x, kumipuyo_y, kumipuyo_r, ojama, event):
        self.field = field
        self.kumipuyos = kumipuyos
        self.score = score
        self.kumipuyo_x = kumipuyo_x
        self.kumipuyo_y = kumipuyo_y
        self.kumipuyo_r = kumipuyo_r
        self.ojama = ojama
        self.event = event

    def render(self):
        result = "event={}, score={}, ojama={}\n".format(self.event.to_string(), self.score, self.ojama)
        kumi_x = self.kumipuyo_x
        kumi_y = self.kumipuyo_y
        if self.kumipuyo_r == 0:
            kumi_y -= 1
        elif self.kumipuyo_r == 1:
            kumi_x += 1
        elif self.kumipuyo_r == 2:
            kumi_y += 1
        else:
            kumi_x -= 1
        for i, puyo in enumerate([EMPTY] * WIDTH + self.field):
            x = i % WIDTH
            y = i / WIDTH
            if i % WIDTH == 0:
                result += "# "
            if x == self.kumipuyo_x and y == self.kumipuyo_y:
                result += render_kumipuyo(self.kumipuyos[0][0], puyo)
            elif x == kumi_x and y == kumi_y:
                result += render_kumipuyo(self.kumipuyos[0][1], puyo)
            else:
                result += render_puyo(puyo)
            if i % WIDTH == WIDTH - 1:
                result += "#"
                if y % 2 == 1:
                    index = y // 2 + 1
                    if index < len(self.kumipuyos):
                        result += "   "
                        for kumipuyo in self.kumipuyos[index]:
                            result += render_puyo(kumipuyo)
                result += "\n"

        return result + "#" * (2 * WIDTH + 3)

    def to_params(self):
        params = dict()
        params["F"] = field_to_string(self.field)
        params["P"] = kumipuyos_to_string(self.kumipuyos)
        params["S"] = str(self.score)
        params["X"] = str(self.kumipuyo_x + 1)
        params["Y"] = str(-(self.kumipuyo_y - HEIGHT - GHOST_HEIGHT))
        params["R"] = str(self.kumipuyo_r)
        params["O"] = str(self.ojama)
        params["E"] = self.event.to_string()
        return params

    @classmethod
    def from_params(cls, params):
        for key, value in params.items():
            if key == "F":
                field = field_from_string(value)
            elif key == "P":
                kumipuyos = kumipuyos_from_string(value)
            elif key == "S":
                score = int(value)
            elif key == "X":
                kumipuyo_x = int(value) - 1
            elif key == "Y":
                kumipuyo_y = HEIGHT + GHOST_HEIGHT - int(value)
            elif key == "R":
                kumipuyo_r = int(value)
            elif key == "O":
                ojama = int(value)
            elif key == "E":
                event = UserEvent.from_string(value)
        return cls(field, kumipuyos, score, kumipuyo_x, kumipuyo_y, kumipuyo_r, ojama, event)

    @classmethod
    def from_json(cls, state, global_deals, num_deals):
        index = state["dealIndex"]
        deals = global_deals[index:index + num_deals]
        return cls(state["blocks"], deals, state["totalScore"], 2, 1, 0, state["pendingNuisance"], UserEvent.from_string("-------"))

class FrameRequest(object):
    def __init__(self, id, players, game_result=None, match_end=None):
        self.id = id
        self.players = players
        self.game_result = game_result
        self.match_end = match_end

    def render(self):
        result = ""
        result += "ID={}, END={}, MATCHEND={}\n".format(self.id, self.game_result, self.match_end)
        player_screens = [p.render() for p in self.players]
        for rows in zip(*[screen.split("\n") for screen in player_screens]):
            result += rows[0]
            result += " " * (40 - len(rows[0]))
            result += rows[1]
            result += "\n"

        return result

    def to_string(self):
        result = "ID={} ".format(self.id)
        if self.game_result:
            result += "END={} ".format(self.game_result)
        if self.match_end:
            result += "MATCHEND={} ".format(self.match_end)
        for prefix, player in [("Y", self.players[0]), ("O", self.players[1])]:
            for key, value in player.to_params().items():
                result += "{}{}={} ".format(prefix, key, value)
        return result.strip()

    @classmethod
    def from_string(cls, payload):
        game_result = None
        match_end = None
        player_params = defaultdict(dict)
        for term in payload.split(" "):
            key, value = term.split("=")
            if key == "ID":
                id = int(value)
                continue
            elif key == "END":
                game_result = int(value)
                continue
            elif key == "MATCHEND":
                match_end = bool(value == "1")
                continue

            index = key[0]
            key = key[1:]
            player_params[index][key] = value

        players = [
            PlayerFrameRequest.from_params(player_params["Y"]),
            PlayerFrameRequest.from_params(player_params["O"]),
        ]
        return cls(id, players, game_result, match_end)

    @classmethod
    def from_json(cls, state):
        player = state["player"]
        state["childStates"] = [state["childStates"][player], state["childStates"][1 - player]]
        players = [PlayerFrameRequest.from_json(child, state["deals"], state["numDeals"]) for child in  state["childStates"]]
        return cls(state["time"] + 1, players)

    def copy(self):
        return self.__class__.from_string(self.to_string())

class FrameResponse(object):
    def __init__(self, id, x, r, pre_x, pre_r, message, mawashi_area):
        self.id = id
        self.x = x
        self.r = r
        self.pre_x = pre_x
        self.pre_r = pre_r
        self.message = message
        self.mawashi_area = mawashi_area

    def to_blocks(self, deal):
        blocks = [EMPTY] * (WIDTH * 3)
        blocks[self.x + WIDTH] = deal[0]
        if self.r == 0:
            blocks[self.x] = deal[1]
        elif self.r == 1:
            blocks[self.x + 1 + WIDTH] = deal[1]
        elif self.r == 2:
            blocks[self.x + 2 * WIDTH] = deal[1]
        else:
            blocks[self.x - 1 + WIDTH] = deal[1]
        return blocks

    @classmethod
    def from_string(cls, payload):
        x = None
        r = None
        pre_x = None
        pre_r = None
        message = None
        mawashi_area = None
        for term in payload.split(" "):
            key, value = term.split("=", 1)
            if key == "ID":
                id = int(value)
            elif key == "X":
                x = int(value) - 1
            elif key == "R":
                r = int(value)
            elif key == "PX":
                pre_x = int(value) - 1
            elif key == "PR":
                pre_r = int(value)
            elif key == "MSG":
                message = value
            elif key == "MA":
                mawashi_area = value
        return cls(id, x, r, pre_x, pre_r, message, mawashi_area)

class FrameInterpolator(object):
    def __init__(self):
        self.id = 0

    def step(self, target):
        frame = FrameRequest.from_json(target)
        if self.id == 0:
            self.id += 1
            frame.id = self.id
            for player in frame.players:
                player.kumipuyos = [(EMPTY, EMPTY)] + player.kumipuyos[:-1]
            yield frame.copy()

            self.id += 1
            frame.id = self.id
            for player in frame.players:
                player.event.next_appeared = True
            yield frame.copy()

            self.id += 1
            frame.id = self.id
            for player in frame.players:
                player.event.next_appeared = False
                player.kumipuyos = player.kumipuyos[1:]
                player.event.grounded = True
            yield frame.copy()
        else:
            self.id += 1
            frame.id = self.id
            for player in frame.players:
                player.event.next_appeared = True
                player.event.grounded = True
            yield frame.copy()

        self.id += 1
        frame.id = self.id
        for player in frame.players:
            player.event.next_appeared = False
            player.event.grounded = False
            player.event.decicion_request = True
        yield frame.copy()

class Driver(object):
    def __init__(self, executable):
        self.process = subprocess.Popen([executable], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def send(self, payload):
        header = struct.pack("I", len(payload))
        self.process.stdin.write(header)
        self.process.stdin.write(payload)
        self.process.stdin.flush()

    def receive(self):
        header = self.process.stdout.read(struct.calcsize("I"))
        size = struct.unpack("I", header)[0]
        return self.process.stdout.read(size)

class FrameDriver(Driver):
    def __init__(self, executable):
        super(FrameDriver, self).__init__(executable)
        self.interpolator = FrameInterpolator()

    def play(self, state):
        for frame in self.interpolator.step(state):
            print frame.render()
            self.send(frame.to_string())
            response = self.receive()
            kumipuyos = frame.players[0].kumipuyos[0]
        return FrameResponse.from_string(response).to_blocks(kumipuyos)


def test_framerequest_parse():
    payload = (
        "ID=1 "
        "YF=000000000000000000000000000000000000000000000000000000000000000000000000 "
        "OF=000000000000000000000000000000000000000000000000000000000000000000000000 "
        "YP=004456 OP=004456 YE=------- OE=------- YX=0 YY=0 YR=0 "
        "OX=0 OY=0 OR=0 YO=0 OO=0 YS=0 OS=0"
    )

    f = FrameRequest.from_string(payload)
    print f.render()

    payload = (
        "ID=464 "
        "YF=000000000000000000000000000000000000000000000000000000550000640077441044 "
        "OF=000000000000000000000000000000000000000000000000770000770000450000650000 "
        "YP=774676 OP=774676 YE=W------ OE=------- YX=1 YY=8 YR=0 "
        "OX=2 OY=4 OR=3 YO=0 OO=0 YS=64 OS=110"
    )

    f = FrameRequest.from_string(payload)

    print f.to_string()

    payload = '''{"time":2,"numColors":4,"numPlayers":2,"numDeals":3,"maxLosses":2,"width":6,"height":12,"childStates":[{"time":2,"totalScore":20,"chainScore":20,"dropScore":20,"leftoverScore":0,"chainNumber":0,"allClearBonus":false,"chainAllClearBonus":false,"pendingNuisance":0,"nuisanceX":0,"gameOvers":0,"width":6,"height":12,"ghostHeight":1,"targetScore":70,"clearThreshold":4,"blocks":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2,0,0,0,0,1,2,4,0,0,0],"effects":[{"type":"puyoDropped","color":2,"to":67,"from":-11,"player":0,"time":1},{"type":"puyoDropped","color":1,"to":72,"from":-12,"player":0,"time":1}],"player":0,"dealIndex":2},{"time":2,"totalScore":20,"chainScore":20,"dropScore":20,"leftoverScore":0,"chainNumber":0,"allClearBonus":false,"chainAllClearBonus":false,"pendingNuisance":0,"nuisanceX":0,"gameOvers":0,"width":6,"height":12,"ghostHeight":1,"targetScore":70,"clearThreshold":4,"blocks":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2,4,0,2,1,0],"effects":[{"type":"puyoDropped","color":2,"to":75,"from":-9,"player":1,"time":1},{"type":"puyoDropped","color":1,"to":76,"from":-8,"player":1,"time":1}],"player":1,"dealIndex":2}],"status":{"terminated":false},"deals":[[2,4],[1,2],[4,4],[1,1],[1,1],[3,3]]}'''

    f = FrameRequest.from_json(json.loads(payload))

    print f.render()
    print f.to_string()

def test_interpolation():
    payload = '''{"time":0,"numColors":4,"numPlayers":2,"numDeals":3,"maxLosses":2,"width":6,"height":12,"childStates":[{"time":0,"totalScore":0,"chainScore":0,"dropScore":0,"leftoverScore":0,"chainNumber":0,"allClearBonus":false,"chainAllClearBonus":false,"pendingNuisance":0,"nuisanceX":0,"gameOvers":0,"width":6,"height":12,"ghostHeight":1,"targetScore":70,"clearThreshold":4,"blocks":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"effects":[],"player":0,"dealIndex":0},{"time":0,"totalScore":0,"chainScore":0,"dropScore":0,"leftoverScore":0,"chainNumber":0,"allClearBonus":false,"chainAllClearBonus":false,"pendingNuisance":0,"nuisanceX":0,"gameOvers":0,"width":6,"height":12,"ghostHeight":1,"targetScore":70,"clearThreshold":4,"blocks":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"effects":[],"player":1,"dealIndex":0}],"status":{"terminated":true,"result":"Timeout"},"deals":[[4,4],[1,3],[1,3]]}'''
    interpolator = FrameInterpolator()
    for frame in interpolator.step(json.loads(payload)):
        print frame.to_string()

def render_log(data):
    for payload in data.split("\n"):
        payload = payload.strip()
        if not payload:
            continue
        f = FrameRequest.from_string(payload)
        print f.render()
        if f.players[0].event:
            sleep(1)
        else:
            sleep(0.01)

"""
driver = FrameDriver('/home/puyoai/puyoai/out/Default/cpu/test_lockit/niina')

payload_0 = '''{"time":0,"numColors":4,"numPlayers":2,"numDeals":3,"maxLosses":2,"width":6,"height":12,"childStates":[{"time":0,"totalScore":0,"chainScore":0,"dropScore":0,"leftoverScore":0,"chainNumber":0,"allClearBonus":false,"chainAllClearBonus":false,"pendingNuisance":0,"nuisanceX":0,"gameOvers":0,"width":6,"height":12,"ghostHeight":1,"targetScore":70,"clearThreshold":4,"blocks":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"effects":[],"player":0,"dealIndex":0},{"time":0,"totalScore":0,"chainScore":0,"dropScore":0,"leftoverScore":0,"chainNumber":0,"allClearBonus":false,"chainAllClearBonus":false,"pendingNuisance":0,"nuisanceX":0,"gameOvers":0,"width":6,"height":12,"ghostHeight":1,"targetScore":70,"clearThreshold":4,"blocks":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],"effects":[],"player":1,"dealIndex":0}],"status":{"terminated":false},"deals":[[1,2],[4,1],[4,3]]}'''
payload_1 = '''{"time":1,"numColors":4,"numPlayers":2,"numDeals":3,"maxLosses":2,"width":6,"height":12,"childStates":[{"time":1,"totalScore":10,"chainScore":10,"dropScore":10,"leftoverScore":0,"chainNumber":0,"allClearBonus":false,"chainAllClearBonus":false,"pendingNuisance":0,"nuisanceX":0,"gameOvers":0,"width":6,"height":12,"ghostHeight":1,"targetScore":70,"clearThreshold":4,"blocks":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,2],"effects":[{"type":"puyoDropped","color":1,"to":76,"from":-8,"player":0,"time":0},{"type":"puyoDropped","color":2,"to":77,"from":-7,"player":0,"time":0}],"player":0,"dealIndex":1},{"time":1,"totalScore":10,"chainScore":10,"dropScore":10,"leftoverScore":0,"chainNumber":0,"allClearBonus":false,"chainAllClearBonus":false,"pendingNuisance":0,"nuisanceX":0,"gameOvers":0,"width":6,"height":12,"ghostHeight":1,"targetScore":70,"clearThreshold":4,"blocks":[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2,0,0,0,0,0,1,0,0,0,0],"effects":[{"type":"puyoDropped","color":2,"to":67,"from":-17,"player":1,"time":0},{"type":"puyoDropped","color":1,"to":73,"from":-11,"player":1,"time":0}],"player":1,"dealIndex":1}],"status":{"terminated":false},"deals":[[1,2],[4,1],[4,3],[4,3],[2,2]]}'''

driver.play(json.loads(payload_0))
driver.play(json.loads(payload_1))
"""
