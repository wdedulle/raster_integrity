import argparse
import os
import sys
from technique_factory import TechniqueFactory, TechniqueType


def parse_tech_args(item):
    if "=" not in item:
        raise argparse.ArgumentTypeError(f"Expected KEY=VALUE, given: {item}")
    key, value = item.split("=", 1)
    return key.strip(), value.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Raster data verification",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--source",
        "-s",
        required=True,
        help="Hash key or Timestamp checking the intregrity",
    )
    parser.add_argument(
        "--arg",
        "-a",
        action="append",
        type=parse_tech_args,
        metavar="KEY=VALUE",
        help="Extra argument for the technique, repeatable (e.g. -a precision=2)",
    )
    parser.add_argument(
        "--technique",
        "-t",
        default="fh",
        required=True,
        help=f"Used technique for verification: \n {TechniqueFactory.help_text()}",
    )

    args = parser.parse_args()

    if not os.path.exists(args.source):
        print(f"ERROR: File not found: {args.source}")
        sys.exit(1)
    try:
        techn = TechniqueFactory.create(args.technique, **dict(args.arg or []))
        print(f"Verification result:{techn.verify(args.source)}")
    except ValueError as e:
        print(f"FOUT: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
