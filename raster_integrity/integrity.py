import argparse
import os
from osgeo import gdal
from technique_factory import TechniqueFactory


def parse_tech_args(item):
    if "=" not in item:
        raise argparse.ArgumentTypeError(f"Expected KEY=VALUE, given: {item}")
    key, value = item.split("=", 1)
    return key.strip(), value.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Execute integrity technique on raster file",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, help="Path of raster file")
    parser.add_argument(
        "--arg",
        "-a",
        action="append",
        type=parse_tech_args,
        metavar="KEY=VALUE",
        help="Extra argument for the technique, repeatable (e.g. -a precision=2)",
    )
    parser.add_argument(
        "--technique", "-t", required=True, help=TechniqueFactory.help_text()
    )
    args = parser.parse_args()

    if not os.path.exists(args.input):
        parser.error(f"File not found: {args.input}")

    try:
        method = TechniqueFactory.create(args.technique, file=args.input)
    except (ValueError, TypeError) as e:
        parser.error(str(e))

    print(method.create_integrity(**dict(args.arg or [])))


if __name__ == "__main__":
    main()
