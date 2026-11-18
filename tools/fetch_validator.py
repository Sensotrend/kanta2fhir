"""Download the HL7 FHIR Validator (validator_cli.jar) into .tools/.

Usage: uv run python tools/fetch_validator.py [--version 7.0.6]
"""

from __future__ import annotations

import argparse
import urllib.request

from kanta2fhir.validate import VALIDATOR_JAR

DEFAULT_VERSION = "7.0.6"
URL = "https://github.com/hapifhir/org.hl7.fhir.core/releases/download/{v}/validator_cli.jar"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default=DEFAULT_VERSION)
    args = parser.parse_args()
    VALIDATOR_JAR.parent.mkdir(parents=True, exist_ok=True)
    url = URL.format(v=args.version)
    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, VALIDATOR_JAR)
    print(f"Saved {VALIDATOR_JAR}")


if __name__ == "__main__":
    main()
