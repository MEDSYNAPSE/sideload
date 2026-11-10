# Rise Labs sideload source

Home-made iPhone and iPad apps as unsigned IPAs, listed in AltStore source format for Feather.

## Add it in Feather

Sources, then add this address:

```
https://raw.githubusercontent.com/MEDSYNAPSE/sideload/main/apps.json
```

Each app then shows in the list. Download, sign with your own certificate, install.

## Publishing

`./publish.py` rebuilds `apps.json` from the IPAs named at the top of the script, then commits and pushes.
This repository is public: an app goes on the list only after its IPA has been checked for private content.
