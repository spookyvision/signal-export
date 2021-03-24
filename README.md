# signal-export

export signal messages to HTML or plain text. Has not been updated to recent signal database versions, PRs welcome.

# prerequisites

-   sqlcipher
-   Signal desktop (the exporter tries to be smart about finding the encrypted database, if it fails, override with `--signal-home`)

# exports by month

Signal chat logs can get very large, so you might want to split things up. There's a `months.py` helper for that. Example, exporting monthly starting from at 2018-06:

```
months.py 2018-06 --extra-fmt='--out=%s.html' --cmd='signal_messages.py --conversation 123-456-abc-def --format html' | while read -r line; do echo $line; $line; done
```

# doxx

```
usage: signal-export.py [-h] [--conversation CONVERSATION]
                        [--group] [--list-groups] [--list-ids]
                        [--start-at START_AT] [--end-at END_AT]
                        [--format FORMAT] [--out OUT] [--signal-home SIGNAL_HOME]

optional arguments:
  -h, --help            show this help message and exit
  --conversation CONVERSATION
                        group name or contact number
  --group               specify that the referenced conversation is a group (default: no); affects formatting of user names
  --list-groups         do not extract a log, list all available groups instead
  --list-ids            do not extract a log, list all available IDs of conversations with individuals instead
  --start-at START_AT   conversation window start date + optional time. Format YYYY-MM-DD or YYYY-MM-DD hh:mm; included (starting exactly at
                        supplied instant)
  --end-at END_AT       conversation window end date + optional time. Format YYYY-MM-DD or YYYY-MM-DD hh:mm; excluded (ending right before
                        supplied instant)
  --format FORMAT       output format ('text' or 'html', default: text)
  --out OUT             file name to write to (default: standard output)
  --signal-home SIGNAL_HOME
                        path to the signal data files (default: OS specific)
```
