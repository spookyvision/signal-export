#!/usr/bin/env python3
import sys, os, subprocess, json, html, argparse, string, re, shutil, errno
from shutil import which
from datetime import datetime, timedelta
from pathlib import Path

"""
create monthly exports for given conversation, starting 2018-06:
months.py 2018-06 --extra-fmt='--out=%s.html' --cmd='signal_messages.py --conversation 11b2e646-a419-407e-8648-f40a35a28b1a --format html' | while read -r line; do echo $line; $line; done
"""


def from_ymd(ts):
    def massage(dt):
        return int(dt.strftime("%s")) * 1000

    try:
        result = datetime.strptime(ts, "%Y-%m-%d %H:%M")
    except:
        result = datetime.strptime(ts, "%Y-%m-%d")
    return massage(result)


def dwim_datetime(ts_or_dt):
    """
    do what I mean!
    """
    try:
        ts_or_dt = int(ts_or_dt)
    except ValueError:
        pass
    if isinstance(ts_or_dt, int):
        return ts_or_dt
    else:
        return from_ymd(ts_or_dt)


def to_ymd(dt1000):
    return datetime.fromtimestamp(dt1000 / 1000).strftime("%Y-%m-%d %H:%M")


def _str_split_chars(s, delims):
    """Split the string `s` by characters contained in `delims`, including the \
    empty parts between two consecutive delimiters"""
    start = 0
    for i, c in enumerate(s):
        if c in delims:
            yield s[start:i]
            start = i + 1
    yield s[start:]


def _str_split_chars_ne(s, delims):
    """Split the string `s` by longest possible sequences of characters \
    contained in `delims`"""
    start = 0
    in_s = False
    for i, c in enumerate(s):
        if c in delims:
            if in_s:
                yield s[start:i]
                in_s = False
        else:
            if not in_s:
                in_s = True
                start = i
    if in_s:
        yield s[start:]


def _str_split_word(s, delim):
    "Split the string `s` by the string `delim`"
    dlen = len(delim)
    start = 0
    try:
        while True:
            i = s.index(delim, start)
            yield s[start:i]
            start = i + dlen
    except ValueError:
        pass
    yield s[start:]


def _str_split_word_ne(s, delim):
    "Split the string `s` by the string `delim`, not including empty parts \
    between two consecutive delimiters"
    dlen = len(delim)
    start = 0
    try:
        while True:
            i = s.index(delim, start)
            if start != i:
                yield s[start:i]
            start = i + dlen
    except ValueError:
        pass
    if start < len(s):
        yield s[start:]


def justify1(tup_list):
    f = lambda t: len(t[0])
    longest = f(max(tup_list, key=f))
    justify_to = longest + 2
    return [t[0].ljust(justify_to) + t[1] for t in tup_list]


def str_split(s, *delims, empty=None):
    """\
found at https://stackoverflow.com/a/12764478/1708913


Split the string `s` by the rest of the arguments, possibly omitting
empty parts (`empty` keyword argument is responsible for that).
This is a generator function.

When only one delimiter is supplied, the string is simply split by it.
`empty` is then `True` by default.
    str_split('[]aaa[][]bb[c', '[]')
        -> '', 'aaa', '', 'bb[c'
    str_split('[]aaa[][]bb[c', '[]', empty=False)
        -> 'aaa', 'bb[c'

When multiple delimiters are supplied, the string is split by longest
possible sequences of those delimiters by default, or, if `empty` is set to
`True`, empty strings between the delimiters are also included. Note that
the delimiters in this case may only be single characters.
    str_split('aaa, bb : c;', ' ', ',', ':', ';')
        -> 'aaa', 'bb', 'c'
    str_split('aaa, bb : c;', *' ,:;', empty=True)
        -> 'aaa', '', 'bb', '', '', 'c', ''

When no delimiters are supplied, `string.whitespace` is used, so the effect
is the same as `str.split()`, except this function is a generator.
    str_split('aaa\\t  bb c \\n')
        -> 'aaa', 'bb', 'c'
"""
    if len(delims) == 1:
        f = _str_split_word if empty is None or empty else _str_split_word_ne
        return f(s, delims[0])
    if len(delims) == 0:
        delims = string.whitespace
    delims = set(delims) if len(delims) >= 4 else "".join(delims)
    if any(len(d) > 1 for d in delims):
        raise ValueError("Only 1-character multiple delimiters are supported")
    f = _str_split_chars if empty else _str_split_chars_ne
    return f(s, delims)


class Condition:
    operator = None

    def __init__(self, field, value):
        self.field = field
        self.value = value

    def __repr__(self):
        return f"{self.field}{self.operator}{self.value}"


class Gt(Condition):
    operator = ">"


class Gte(Condition):
    operator = ">="


class Lt(Condition):
    operator = "<"


class Lte(Condition):
    operator = "<="


class Eq(Condition):
    operator = "="


class Like(Condition):
    operator = " LIKE "


class Sender(Eq):
    field = ""


class SqlString:
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        escaped = self.value.replace("'", "''")
        return f"'{escaped}'"


class Where:
    def __init__(self):
        self.conditions = []

    def __repr__(self):
        if len(self.conditions) == 0:
            return ""
        else:
            anded = " and ".join(repr(c) for c in self.conditions)
            return f" where {anded}"

    def add_sent_gte(self, timestamp):
        self.conditions.append(Gte("sent_at", dwim_datetime(timestamp)))

    def add_sent_lt(self, timestamp):
        self.conditions.append(Lt("sent_at", dwim_datetime(timestamp)))

    def add_between(self, old, new):
        # time intervals should be half-open
        # http://wrschneider.github.io/2014/01/07/time-intervals-and-other-ranges-should.html
        # https://web.archive.org/web/20190520230211/http://wrschneider.github.io/2014/01/07/time-intervals-and-other-ranges-should.html
        self.conditions.append(Gte("sent_at", dwim_datetime(old)))
        self.conditions.append(Lt("sent_at", dwim_datetime(new)))

    def add_conversation_id(self, cid):
        self.conditions.append(Eq("conversationId", SqlString(cid)))
        # self.conditions.append(Eq('json_tree.key', SqlString('conversationId')))
        # self.conditions.append(Eq('json_tree.value', SqlString(cid)))


class Query:
    def __init__(self):
        self.where = Where()

    def __repr__(self):
        return f"""select distinct messages.json from messages, json_tree(messages.json){self.where} order by sent_at;"""


class SignalPaths:
    base = None
    mirror = None

    @classmethod
    def default(cls):
        if sys.platform == "darwin":
            return OsxPaths()
        else:
            return LinuxPaths()

    @property
    def config(self):
        return os.path.join(self.base, "config.json")

    @property
    def db(self):
        return os.path.join(self.base, "sql", "db.sqlite")

    def get_attachment(self, subpath):
        src = os.path.join(self.base, "attachments.noindex", subpath)
        if not self.mirror:
            return src
        if self.mirror:
            dst_dir = os.path.join(self.mirror, os.path.dirname(subpath))
            try:
                os.makedirs(dst_dir)
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise
            return shutil.copy(src, dst_dir)


class OsxPaths(SignalPaths):
    @property
    def base(self):
        return os.path.join(Path.home(), "Library", "Application Support", "Signal")


class LinuxPaths(SignalPaths):
    @property
    def base(self):
        return os.path.join(Path.home(), ".config", "Signal")


class CustomPaths(SignalPaths):
    def __init__(self, base):
        self.base = base


class DBI:
    def __init__(self, paths, compact_lookup=True):
        self.paths = paths
        self.names = {}
        self.compact_lookup = compact_lookup
        with open(self.paths.config, "rb") as fh:
            self.key = json.load(fh)["key"]

    def execute(self, sql):
        # print(f'SQL> {sql}')
        data = subprocess.check_output(
            [
                "sqlcipher",
                "-list",
                "-noheader",
                self.paths.db,
                f"PRAGMA key = \"x'{self.key}'\"; {sql}",
            ]
        ).decode("utf-8")

        data = re.sub("^ok\n", "", data)
        return data[
            :-1
        ]  # remove last newline (it's otherwise valid so we're not gonna use any strip() funcs. Probably breaks on windows.)

    def execute_list(self, sql):
        return self.execute(sql).split("\n")

    def lookup_tup(self, contact_id_or_phone, compact=True):
        if compact and self.compact_lookup:
            return "", ""
        if contact_id_or_phone in self.names:
            return self.names[contact_id_or_phone]
        # conversation_cid = contact_id.replace('+','')
        data = self.execute(
            f"select quote(name), quote(profileName) from conversations where id='{contact_id_or_phone}' or e164='{contact_id_or_phone}'"
        )
        if not data:
            data = "?"
        else:
            parts = [part for part in self.parse_result(data) if part]
            if not parts:
                data = "?"
            else:
                data = "|".join(parts)
        self.names[contact_id_or_phone] = contact_id_or_phone, data
        return self.names[contact_id_or_phone]

    def lookup(self, contact_id_or_phone, compact=True):
        result = self.lookup_tup(contact_id_or_phone, compact)
        if not result[0] and not result[1]:
            return ""
        return f"{result[1]} ({result[0]})"

    def find_group_id(self, name):
        result = self.execute(f"select id from conversations where name='{name}'")
        if not result:
            raise SystemExit("Group not found")
        return result

    def list_groups(self):
        for info in self.execute_list(
            "select id, members, name from conversations where type='group'"
        ):
            sid, members, name = info.split("|", maxsplit=2)
            members = members.split(" ")
            print(f"Group:\n\x1b[0;37;40m{sid} \x1b[0m{name}")
            print("Members:")
            # members = justify1(list(self.lookup(member, False) for member in members))
            def format_member(m):
                mid, data = m
                return f"\x1b[0;37;40m{mid} \x1b[0m{data}"

            print(
                "\n".join(
                    format_member(self.lookup_tup(member, False)) for member in members
                )
            )
            print("----------------------")

    def list_ids(self):
        print("id | profileName | profileFullName | profileFamilyName | number")
        for info in self.execute_list(
            "select distinct id, profileName, profileFullName, profileFamilyName, e164 from conversations order by id"
        ):
            print(" | ".join(info.split("|")))

    def parse_result(self, raw_result):
        result = []
        for match in re.findall(r"('(''|[^'])*')|(NULL)|([0-9\.]*)", raw_result):
            if match[0]:
                result.append(match[0][1:-1].replace("''", "'"))
            elif match[2]:
                result.append(None)
            elif match[3]:
                result.append(eval(match[3]))
        return result

    def process_with_handler(self, query, handler):
        data = self.execute(query)
        handler.begin()
        handler.add_info(repr(query))
        for item in str_split(data, "\n"):
            handler.eat(item.strip(), self.lookup)
        handler.end()


class Textizer:
    def __init__(self, paths, out):
        self.paths = paths
        self.out = out

    def begin(self):
        pass

    def add_info(self, info):
        pass

    def end(self):
        pass

    def eat(self, item, lookup):
        if not item:
            return
        data = json.loads(item)
        if (
            "expirationTimerUpdate" in data
            or data["type"] == "keychange"
            or not "body" in data
        ):
            return
        sent_at = to_ymd(data["sent_at"])
        if data["type"] == "incoming":
            # print(f'INCOMING {data}')
            self.out.write(f"{lookup(data['source'])} {sent_at}:" + "\n")
        elif data["type"] == "outgoing":
            self.out.write(f"(you) {sent_at}" + "\n")
        else:
            self.out.write(("??? " + data["type"] + "\n"))
        if "quote" in data:
            quote = data["quote"]
            if quote and "text" in quote:
                self.out.write(f"> {lookup(quote['author'], compact=False)}" + "\n")
                self.out.write(f"> {quote['text']}" + "\n")
        for att in data["attachments"]:
            if "path" in att:
                path = self.paths.get_attachment(att["path"])
                self.out.write(f"attachment file: {path}" + "\n")
            self.out.write(json.dumps(att, indent=4) + "\n")
        if data["body"]:
            self.out.write(data["body"] + "\n")
        self.out.write("-------\n")


class Htmlizer:
    template = """\
<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <style type="text/css">
    body {
        background-color: #fff;
        color: #000;
        font-family: Arial, Helvetica, sans-serif;
    }
    img {
        max-height: 60vh;
        max-width: 50vw;
    }
    a, a:hover { color: inherit; } 
    a.quote { text-decoration: none; }
    a.message_id { 
        display: block;
        clear:both;
        }
    div.message {
        display: inline-block;
        max-width: 75%;
        border-radius: 0.7em;
        padding-top: 1em;
        padding-right: 1em;
        padding-bottom: 0.5em;
        padding-left: 1em;
        display: inline-block;
        margin: 0.4em 0.8em;
    }
    div.incoming {
        background-color: #ddd;
        float: left;
        clear: both;
    }
    div.outgoing {
        background-color: #39f;
        color: #fff;
        float: right;
        clear: both;
    }
    div.quote {
        background-color: #9cf;
        color: #000;
    }
    div.incoming div.quote {
        border-left:3px solid #38f;
    }
    div.outgoing div.quote {
        border-left:3px solid #fff;
    }
    div.attachments {
        margin: 5px;
    }
    div.sender_info {
        font-size: 0.7em;
        opacity: 0.6;
        text-align: right;
        margin-top: 0.5em;
    }
    div.quote div.sender_info {
        margin-top: -0.8em !important;
    }
    span.single_emoji {
        font-size: 3em;
    }
    </style>
</head>
<body>"""

    def __init__(self, paths, out):
        self.paths = paths
        self.out = out
        self.url_detect = re.compile(
            "(https?|ftp)(://[^\\s/$.?#].[^\\s]*)", flags=re.IGNORECASE | re.DOTALL
        )

    def begin(self):
        self.out.write(self.template)

    def add_info(self, info):
        s = "\n<!-- " + info + " -->\n"
        self.out.write(s)

    def end(self):
        self.out.write("</body></html>")

    def eat(self, item, lookup):
        if not item:
            return
        data = json.loads(item)
        if (
            "expirationTimerUpdate" in data
            or data["type"] == "keychange"
            or not "body" in data
        ):
            return

        quote_elem = ""
        if "quote" in data and data["quote"]:
            quote = data["quote"]
            has_text_key = "text" in quote
            has_attachments_key = "attachments" in quote
            if quote and (has_text_key or has_attachments_key):
                sender_name = lookup(quote["author"], compact=False)
                sender_info_elem = f'<div class="sender_info">{sender_name}</div>'
                attachments_elem = ""
                attachments = []
                if has_attachments_key:
                    for att in quote["attachments"]:
                        if not att["thumbnail"]:
                            img_elem = '<div style="border:1px solid red">MISSING</div>'
                        else:
                            thumb_path = self.paths.get_attachment(
                                att["thumbnail"]["path"]
                            )
                            img_elem = f'<img src="{thumb_path}">'
                        attachments.append(img_elem)
                if attachments:
                    attachments_elem = (
                        '<div class="attachments">' + "\n".join(attachments) + "</div>"
                    )
                else:
                    attachments_elem = ""

                quote_content = quote["text"]
                if quote_content is None:
                    quote_content = ""
                quote_content = html.escape(quote_content)
                quote_elem = f"<a class=\"quote\" href=\"#{quote['id']}\"><div class=\"message quote\">{sender_info_elem}<br>{attachments_elem}{quote_content}</div></a><br>\n"

        attachments = []
        display_full = len(data["attachments"]) < 2
        for att in data["attachments"]:
            try:
                path = self.paths.get_attachment(att["path"])
            except:
                print("NOOOO", file=sys.stderr)
                print(att, file=sys.stderr)
                continue
            content_type = att["contentType"]
            if content_type.startswith("image") and "path" in att:
                img_path = path
                if display_full:
                    thumb_path = img_path
                else:
                    thumb_path = self.paths.get_attachment(att["thumbnail"]["path"])
                img_elem = f'<img src="{thumb_path}">'
                a_elem = f'<a href="{img_path}">{img_elem}</a>'
                attachments.append(a_elem)
            elif content_type.startswith("video"):
                video_elem = f'<video controls loop width="500"><source src="{path}" type="{content_type}"></video>'
                attachments.append(video_elem)
            elif content_type.startswith("audio"):
                audio_elem = f'<audio controls><source src="{path}" type="{content_type}"></video>'
                attachments.append(audio_elem)
            elif content_type.startswith("text"):
                with open(path, "r") as fh:
                    text = fh.read()
                inline_text_elem = f"<div>{text}</div>"
                attachments.append(inline_text_elem)
            else:
                download = f"<a download=\"{att['fileName']}\" href=\"{path}\">{att['fileName']}</a>"
                attachments.append(
                    download
                    + "<pre>"
                    + html.escape(json.dumps(att, indent=4))
                    + "</pre>"
                )
        if attachments:
            attachments_elem = (
                '<div class="attachments">' + "\n".join(attachments) + "</div>"
            )
        else:
            attachments_elem = ""
        if data["body"]:
            body = html.escape(data["body"]).replace("\n", "<br>\n")
            body = re.sub(self.url_detect, r'<a href="\1\2">\1\2</a>', body)

            if len(body) == 1:  # this does not respect modifiers - TODO
                code_point = ord(body)
                is_emoji = (0x2700 <= code_point <= 0x27BF) or (
                    0x1F300 <= code_point <= 0x1F9FF
                )
                if is_emoji:
                    body = f'<span class="single_emoji">{body}</span>'

        else:
            body = ""
        if data["type"] == "incoming":
            sender_name = lookup(data["source"]) + " "
        else:
            sender_name = ""
        sent_at = data["sent_at"]
        sender_info_elem = (
            f'<div class="sender_info">{sender_name}{to_ymd(sent_at)}</div>'
        )
        content_elem = f"""\
<a class="message_id" name="{sent_at}"></a>
<div class="message {data['type']}">
{quote_elem}
{attachments_elem}
{body}
{sender_info_elem}
</div>
"""
        has_content = quote_elem or attachments_elem or body
        if has_content:
            self.out.write(content_elem)


def main():
    if which("sqlcipher") is None:
        raise SystemExit("required dependency not found: sqlcipher")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--conversation", action="store", help="group name or contact number"
    )
    parser.add_argument(
        "--group",
        action="store_true",
        help="specify that the referenced conversation is a group (default: no); affects formatting of user names",
    )
    parser.add_argument(
        "--list-groups",
        action="store_true",
        help="do not extract a log, list all available groups instead",
    )
    parser.add_argument(
        "--list-ids",
        action="store_true",
        help="do not extract a log, list all available IDs of conversations with individuals instead",
    )
    parser.add_argument(
        "--start-at",
        action="store",
        help="conversation window start date + optional time. Format YYYY-MM-DD or YYYY-MM-DD hh:mm; included (starting exactly at supplied instant)",
    )
    parser.add_argument(
        "--end-at",
        action="store",
        help="conversation window end date + optional time. Format YYYY-MM-DD or YYYY-MM-DD hh:mm; excluded (ending right before supplied instant)",
    )
    parser.add_argument(
        "--format",
        action="store",
        default="text",
        help="output format ('text' or 'html', default: text)",
    )
    parser.add_argument(
        "--out",
        action="store",
        default=None,
        help="file name to write to (default: standard output)",
    )
    parser.add_argument(
        "--signal-home",
        action="store",
        default=None,
        help="path to the signal data files (default: OS specific)",
    )
    args = parser.parse_args()

    if args.signal_home:
        paths = CustomPaths(base=args.signal_home)
    else:
        paths = SignalPaths.default()

    if args.out is None:
        out = sys.stdout
    else:
        out = open(
            args.out, "w", encoding="utf-8"
        )  # yes, we are opinionated, also the html meta tag kinda forces this
        paths.mirror = os.path.join(os.path.dirname(args.out), "attachments")

    if args.format == "text":
        handler = Textizer(paths, out)
    elif args.format == "html":
        handler = Htmlizer(paths, out)
    else:
        raise SystemExit("unknown output format")

    dbi = DBI(paths, compact_lookup=not args.group)
    if args.list_groups:
        dbi.list_groups()
        raise SystemExit
    if args.list_ids:
        dbi.list_ids()
        raise SystemExit
    query = Query()
    if args.start_at:
        query.where.add_sent_gte(dwim_datetime(args.start_at))
    if args.end_at:
        query.where.add_sent_lt(dwim_datetime(args.end_at))

    conversation_id = args.conversation

    if not conversation_id:
        parser.print_help()
        raise SystemExit

    query.where.add_conversation_id(conversation_id)

    dbi.process_with_handler(query, handler)


if __name__ == "__main__":
    main()
