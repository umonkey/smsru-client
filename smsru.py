# encoding=utf-8

"""An sms.ru client.

Provides a class that lets you use the sms.ru API to send messages and verify
their status.  Supports digest authentication.

Configuration is looked for in files ~/.config/smsru.conf and /etc/smsru.conf,
whichever is found first.  Example config for simple auth:

  key=00000000-0000-0000-0000-000000000000
  sender=MyName

Example config for enhanced auth:

  key=00000000-0000-0000-0000-000000000000
  sender=MyName
  login=alice
  password=secret

To use in a python program:

  import smsru
  cli = smsru.Client()
  cli.send("+79112223344", u"привет лунатикам")

To use with CLI:

  python smsru.py send "+79112223344" "привет лунатикам"
"""

import hashlib
import os
import time
import urllib
import urllib2


CONFIG_FILES = ("~/.config/smsru.conf", "/etc/smsru.conf")

SEND_STATUS = {
    100: "Message accepted",
    201: "Out of money",
    202: "Bad recipient",
    203: "Message text not specified",
    204: "Bad sender (unapproved)",
    205: "Message too long",
    206: "Day message limit reached",
    207: "Can't send messages to that number",
    208: "Wrong time",
    209: "Blacklisted recipient",
}

STATUS_STATUS = {
    -1: "Message not found",
    100: "Message is in the queue",
    101: "Message is on the way to the operator",
    102: "Message is on the way to the recipient",
    103: "Message delivered",
    104: "Message failed: out of time",
    105: "Message failed: cancelled by the operator",
    106: "Message failed: phone malfunction",
    107: "Message failed, reason unknown",
    108: "Message declined",
}

COST_STATUS = {
    100: "Success"
}

__author__ = "Justin Forest"
__email__ = "hex@umonkey.net"
__license__ = "GPL"
__all__ = ["Client"]


class NotConfigured(Exception):
    pass


class WrongKey(Exception):
    pass


class InternalError(Exception):
    pass


class Unavailable(Exception):
    pass


class Client(object):
    def __init__(self):
        self.config = self._load_config()
        if self.config is None:
            raise NotConfigured("Config file not found, options: " + " ".join(CONFIG_FILES))
        if "key" not in self.config:
            raise NotConfigured("API key not set.")
        self._token = None
        self._token_ts = 0

    def _load_config(self):
        for fn in CONFIG_FILES:
            fn = os.path.expanduser(fn)
            if os.path.exists(fn):
                raw = file(fn, "rb").read().strip().decode("utf-8")
                items = [[x.strip() for x in line.split("=", 1)] for line in raw.split("\n")]
                return dict(items)
        return None

    def _call(self, method, args):
        """Calls a remote method."""
        if not isinstance(args, dict):
            raise ValueError("args must be a dictionary")
        args["api_id"] = self.config["key"]

        if method in ("sms/send", "sms/cost"):
            login = self.config.get("login", "").lstrip("+")
            password = self.config.get("password")
            if login and password:
                args["login"] = login
                args["token"] = self._get_token()
                args["sig"] = hashlib.md5(password + args["token"]).hexdigest()
                del args["api_id"]

        url = "http://sms.ru/%s?%s" % (method, urllib.urlencode(args))
        # print url
        res = urllib2.urlopen(url).read().strip().split("\n")
        if res[0] == "200":
            raise WrongKey("The supplied API key is wrong")
        elif res[0] == "210":
            raise InternalError("GET used when POST must have been")
        elif res[0] == "211":
            raise InternalError("Unknown method")
        elif res[0] == "220":
            raise Unavailable("The service is temporarily unavailable")
        elif res[0] == "301":
            raise NotConfigured("Wrong password")
        return res

    def _get_token(self):
        """Returns a token.  Refreshes it if necessary."""
        if self._token_ts < time.time() - 500:
            self._token = None
        if self._token is None:
            self._token = self.token()
            self._token_ts = time.time()
        return self._token

    def send(self, to, message, express=False, test=False):
        """Sends the message to the specified recipient.  Returns a numeric
        status code, its text description and, if the message was successfully
        accepted, its reference number."""
        if not isinstance(message, unicode):
            raise ValueError("message must be a unicode")
        args = {"to": to, "text": message.encode("utf-8")}
        if "sender" in self.config:
            args["from"] = self.config["sender"]
        if express:
            args["express"] = "1"
        if test:
            args["test"] = "1"
        res = self._call("sms/send", args)
        if res[0] != "100":
            res.append(None)
        return int(res[0]), SEND_STATUS.get(int(res[0]), "Unknown status"), res[1]

    def status(self, msgid):
        """Returns message status."""
        res = self._call("sms/status", {"id": msgid})
        code = int(res[0])
        text = STATUS_STATUS.get(code, "Unknown status")
        return code, text

    def cost(self, to, message):
        """Prints the cost of the message."""
        res = self._call("sms/cost", {"to": to, "text": message.encode("utf-8")})
        if res[0] != "100":
            res.extend([None, None])
        return int(res[0]), COST_STATUS.get(int(res[0]), "Unknown status"), res[1], res[2]

    def balance(self):
        """Returns your current balance."""
        res = self._call("my/balance", {})
        if res[0] == "100":
            return float(res[1])
        raise Exception(res[0])

    def limit(self):
        """Returns the remaining message limit."""
        res = self._call("my/limit", {})
        if res[0] == "100":
            return int(res[1])
        raise Exception(res[0])

    def token(self):
        """Returns a token."""
        return self._call("auth/get_token", {})[0]


if __name__ == "__main__":
    import sys

    try:
        if len(sys.argv) == 4 and sys.argv[1] == "send":
            print Client().send(sys.argv[2], sys.argv[3].decode("utf-8"))
            exit(0)

        if len(sys.argv) == 4 and sys.argv[1] == "send-test":
            print Client().send(sys.argv[2], sys.argv[3].decode("utf-8"), test=True)
            exit(0)

        elif len(sys.argv) > 2 and sys.argv[1] == "status":
            cli = Client()
            for msgid in sys.argv[2:]:
                status = cli.status(msgid)
                print "%s = %s" % (msgid, status)
            exit(0)

        elif len(sys.argv) == 4 and sys.argv[1] == "cost":
            res = Client().cost(sys.argv[2], sys.argv[3].decode("utf-8"))
            print "Status=%s (%s), cost=%s, length=%s" % res
            exit(0)

        elif len(sys.argv) == 2 and sys.argv[1] == "balance":
            print Client().balance()
            exit(0)

        elif len(sys.argv) == 2 and sys.argv[1] == "limit":
            print Client().limit()
            exit(0)

        elif len(sys.argv) == 2 and sys.argv[1] == "token":
            print Client().token()
            exit(0)
    except Exception, e:
        print "ERROR: %s." % e
        exit(1)

    print "Usage:"
    print "  %s balance                   -- show current balance" % sys.argv[0]
    print "  %s cost number message       -- show message cost" % sys.argv[0]
    print "  %s limit                     -- show remaining daily message limit" % sys.argv[0]
    print "  %s send number message       -- send a message" % sys.argv[0]
    print "  %s send-test number message  -- test sending a message" % sys.argv[0]
    print "  %s status msgid...           -- check message status" % sys.argv[0]
    print "  %s token                     -- prints a token" % sys.argv[0]
    exit(1)
