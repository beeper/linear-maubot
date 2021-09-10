#!/usr/bin/python3
import requests
import json

def unified_to_unicode(unified: str) -> str:
  return ("".join(fr"\U{chunk:0>8}"
                 for chunk in unified.split("-"))
            .encode("ascii")
            .decode("unicode_escape"))

data = requests.get("https://raw.githubusercontent.com/iamcal/emoji-data/master/emoji.json").json()
emojis = {unified_to_unicode(emoji["unified"]): emoji["short_name"] for emoji in data}
with open("emoji.json", "w") as file:
  json.dump(emojis, file, ensure_ascii=False)
