#!/usr/bin/python

from marshmallow import Schema, fields, post_load, exceptions
from pathlib import Path

import argparse
import logging
import shutil
import os
import sys
import yaml
import yaml.scanner


class CustomFormatter(logging.Formatter):
    """Custom logger formatter"""

    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: grey + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def list_git():
    with os.popen('git ls-files') as git_files:
        for line in git_files:
            yield line.rstrip('\n')


class LicenseSchema(Schema):
    """License entry schema validator"""
    name = fields.String(required=True)
    copyright = fields.String()
    info = fields.String()

    @post_load
    def make_object(self, data, **kwargs):
        return License(**data)


class FileSchema(Schema):
    """File entry schema validator"""
    name = fields.String(required=True)
    info = fields.String()
    source = fields.List(fields.String())
    version = fields.String()

    @post_load
    def make_object(self, data, **kwargs):
        return File(**data)


class LinkSchema(Schema):
    """Link entry schema validator"""
    name = fields.String(required=True)
    target = fields.String(required=True)

    @post_load
    def make_object(self, data, **kwargs):
        return Link(**data)


class EntrySchema(Schema):
    """Entry schema validator"""
    name = fields.String(required=True)
    description = fields.String(required=True)
    category = fields.List(fields.String(required=True), required=True)
    vendor = fields.String(required=True)
    license = fields.Nested(LicenseSchema, required=True)
    info = fields.String(required=True)
    files = fields.List(fields.Nested(FileSchema), required=True)
    links = fields.List(fields.Nested(LinkSchema))

    @post_load
    def make_object(self, data, **kwargs):
        return Entry(**data)


class WhenceSchema(Schema):
    """Whole file schema validator"""
    entries = fields.List(fields.Nested(EntrySchema), required=True)


class File:
    def __init__(self, name, info=None, source=None, version=None):
        self.name = name
        self.info = info
        self.source = source
        self.version = version

    def __repr__(self):
        return "<File(name={self.name}, " \
               "info={self.info}, " \
               "source={self.source}, " \
               "version={self.version})>".format(self=self)

    def __str__(self):
        return "  - {self.name}".format(self=self)


class License:
    def __init__(self, name, copyright=None, info=None):
        self.name = name
        self.copyright = copyright
        self.info = info

    def __repr__(self):
        return "<License(name={self.name}, " \
               "copyright={self.copyright}, " \
               "info={self.info})>".format(self=self)

    def __str__(self):
        result = "  Name: {self.name}".format(self=self)
        if self.copyright is not None:
            result += "\n  Copyright: {self.copyright}".format(self=self)
        if self.info is not None:
            result += "\n  Info: {self.info}".format(self=self)
        return result


class Link:
    def __init__(self, name, target):
        self.name = name
        self.target = target

    def __repr__(self):
        return "<Link (name={self.name}, target={self.target})>".format(self=self)

    def __str__(self):
        return "  - {self.name} -> {self.target}".format(self=self)


class Entry:
    def __init__(self, name, description, category, vendor, license, info, files, links=None):
        self.name = name
        self.description = description
        self.category = category
        self.vendor = vendor
        self.license = license
        self.info = info
        self.files = files
        self.links = links

    def __repr__(self):
        return "<Entry (name={self.name}, description={self.description}, " \
               "category={self.category}, vendor={self.vendor}, license={self.license}, " \
               "info={self.info}, files={self.files}, links={self.links})>".format(self=self)

    def __str__(self):
        try:
            size = sum(Path(itm.name).stat().st_size for itm in self.files)
        except FileNotFoundError as e:
            logger.warning("Error calculation file size: {}!".format(e))
            size = 0

        return "Entry: {self.name}\n" \
               "Description: {self.description}\n" \
               "Categories:\n{categories}\n" \
               "Vendor: {self.vendor}\n" \
               "License:\n{self.license}\n" \
               "Info:\n{self.info}\n" \
               "Size: {size:,} bytes\n" \
               "Files:\n{files}\n" \
               "Links:\n{links}\n" \
               "--------\n" \
            .format(
                self=self,
                categories="\n".join("  - {} ".format(itm) for itm in self.category),
                files="\n".join("{}".format(itm) for itm in self.files),
                links="\n".join("{}".format(itm) for itm in self.links) if self.links is not None else "None",
                size=size
            )


class WhenceLoader:
    def __init__(self, whence_file="WHENCE.yaml"):
        """Load WHENCE.yaml file and initialize object"""
        try:
            loaded = yaml.safe_load(Path(whence_file).read_text())
            schema = WhenceSchema()
            self.whence_content = schema.load(loaded)
        except FileNotFoundError as e:
            logger.error("WHENCE-file '{}' not found: {}!".format(args.whence, e))
            sys.exit(1)
        except yaml.scanner.ScannerError as e:
            logger.error("Format of WHENCE-file is incorrect: {}!".format(e))
            sys.exit(1)
        except exceptions.ValidationError as e:
            logger.error("Schema of WHENCE-file is incorrect: {}!".format(e))
            sys.exit(1)

    def _install(self, root, source):
        """Install requested file"""
        if not Path(source).exists():
            logger.error("Source file {} does not exists".format(source))
            return

        fullpath = Path(root) / Path(source)
        fullpath.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        if fullpath.exists():
            logger.warning("Target file {} exists, overwriting".format(fullpath))

        logger.info("Copying {} to {}".format(source, fullpath))
        shutil.copyfile(source, fullpath)

    def _install_symlink(self, root, link, target):
        """Install requested symlink"""
        linkpath = Path(root) / Path(link)
        parentpath = linkpath.parent
        # Create parentpath early since targetpath may require existing path
        parentpath.mkdir(mode=0o755, parents=True, exist_ok=True)

        targetpath = parentpath / Path(target)
        if not targetpath.exists():
            logger.error("Source file {} does not exists".format(targetpath))
            return

        if linkpath.exists():
            logger.warning("Target file {} exists, overwriting".format(linkpath))
            linkpath.unlink()

        logger.info("Making link {} to {}".format(linkpath, target))
        linkpath.symlink_to(target)

    def check(self):
        """Check WHENCE.yaml content, compare file lists with actual files in repo"""
        # Ignorable files
        known_paths = [".asc", "check_whence.py", "configure", "copy-firmware.sh",
                       "firmware-install.py", "ChangeLog", "Makefile", "NOTICE.txt",
                       "README", "WHENCE", "WHENCE.yaml"]
        # Ignorable license names
        known_licenses = ["Redistributable", "Unknown"]
        # Get content (files, sources, licenses)
        entries = self.list()
        # Get all filenames from files section
        whence_files = set(itm.name for itm in entries for itm in itm.files)
        # Append licenses files
        whence_files.update(set(itm.license.name for itm in entries if itm.license.name not in known_licenses))
        # Append source entries from files section (only regular files)
        # If source points to directory, all files recursively
        # from that directory will be added
        for itm in set(
                itm for itm in list(
                    itm.source for itm in entries for itm in itm.files if itm.source is not None)
                for itm in itm):
            if Path(itm).is_dir():
                whence_files.update(list(str(file) for file in Path(itm).rglob("*") if file.is_file()))
            else:
                whence_files.add(itm)

        ret = 0

        output = set(list_git())

        for name in output.difference(whence_files):
            if name.endswith(tuple(known_paths)):
                continue
            logger.error("'{}' not listed in WHENCE.yaml".format(name))
            ret = 1

        for name in whence_files.difference(output):
            logger.error("'{}' listed in WHENCE.yaml does not exist".format(name))
            ret = 1

        return ret

    def get(self, name):
        """
        Returns info about particular entry_name or empty list if no such entry
        """
        return list(filter(lambda d: d.name == name, self.whence_content["entries"]))

    def list(self, names=None, vendors=None, categories=None, licenses=None):
        """Return list of entries that matches provided filters"""
        return list(
            filter(lambda d: (
                    (names is None or d.name in names) and
                    (vendors is None or d.vendor in vendors) and
                    (licenses is None or d.license.name in licenses) and
                    (categories is None or any(map(lambda each: each in d.category, categories)))
            ), self.whence_content["entries"]))

    def install(self, destination, names=None, vendors=None, categories=None, licenses=None):
        """Install files from filtered query list"""
        entries = self.list(names, vendors, categories, licenses)

        for entry in entries:
            for file in entry.files:
                self._install(destination, file.name)

            if entry.links is not None:
                for link in entry.links:
                    self._install_symlink(destination, link.name, link.target)


if __name__ == "__main__":
    logger = logging.getLogger("firmware-install")

    # create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setFormatter(CustomFormatter())

    logger.addHandler(ch)

    def do_check(args):
        content = WhenceLoader(args.whence)
        sys.exit(content.check())

    def do_info(args):
        content = WhenceLoader(args.whence)
        for entry in content.list(
                names=None if args.names is None else args.names.split(","),
                vendors=None if args.vendors is None else args.vendors.split(","),
                licenses=None if args.licenses is None else args.licenses.split(","),
                categories=None if args.categories is None else args.categories.split(",")
        ):
            print(entry)
        sys.exit(0)

    def do_install(args):
        content = WhenceLoader(args.whence)
        content.install(
            args.destination,
            names=None if args.names is None else args.names.split(","),
            vendors=None if args.vendors is None else args.vendors.split(","),
            licenses=None if args.licenses is None else args.licenses.split(","),
            categories=None if args.categories is None else args.categories.split(",")
        )


    def do_list(args):
        content = WhenceLoader(args.whence)
        entries = content.list()

        if args.licenses:
            licenses = sorted(set(itm.license.name for itm in entries))
            print("\n".join(licenses))
        elif args.vendors:
            vendors = sorted(set(itm.vendor for itm in entries))
            print("\n".join(vendors))
        elif args.categories:
            categories = sorted(set(itm for itm in entries for itm in itm.category))
            print("\n".join(categories))
        else:
            # Default - list names
            names = sorted(set(itm.name for itm in entries))
            print("\n".join(names))


    # Main
    parser = argparse.ArgumentParser(
        prog="firmware-install.py",
        description="Query info and installs firmware files"
    )
    parser.add_argument("-V", "--verbose", help="Specify verbose level (DEBUG, INFO, WARNING, ERROR or CRITICAL, "
                                                "default is WARNING)", default="WARNING")
    subparsers = parser.add_subparsers(title="Commands", description="valid subcommands")
    parser_check = subparsers.add_parser("check", help="Check WHENCE.yaml content and files")
    parser_info = subparsers.add_parser("info", help="Get info about entries that comply filtered query")
    parser_install = subparsers.add_parser("install", help="Install firmware files that comply filtered query")
    parser_list = subparsers.add_parser("list", help="List all unique entries for provided query")
    parser_check.set_defaults(func=do_check)
    parser_info.set_defaults(func=do_info)
    parser_install.set_defaults(func=do_install)
    parser_list.set_defaults(func=do_list)

    parser_check.add_argument("-w", "--whence", help="Specify custom WHENCE.yaml file (default is WHENCE.yaml)",
                              default="WHENCE.yaml")

    group_list = parser_list.add_mutually_exclusive_group()
    group_list.add_argument("-n", "--names", action="store_true", help="Get all unique entry names")
    group_list.add_argument("-v", "--vendors", action="store_true", help="Get all unique vendor names")
    group_list.add_argument("-c", "--categories", action="store_true", help="Get all unique category names")
    group_list.add_argument("-l", "--licenses", action="store_true", help="Get all unique license names")
    parser_list.add_argument("-w", "--whence", help="Specify custom WHENCE.yaml file (default is WHENCE.yaml)",
                             default="WHENCE.yaml")

    for i in [parser_info, parser_install]:
        i.add_argument("-n", "--names", help="Query filter with entry names (comma separated)")
        i.add_argument("-v", "--vendors", help="Query filter with vendor names (comma separated)")
        i.add_argument("-c", "--categories", help="Query filter with categories (comma separated)")
        i.add_argument("-l", "--licenses", help="Query filter with licenses (comma separated)")
        i.add_argument("-w", "--whence", help="Specify custom WHENCE.yaml file (default is WHENCE.yaml)",
                       default="WHENCE.yaml")
    parser_install.add_argument("-d", "--destination", help="Destination directory (default is /lib/firmware)",
                                default="/lib/firmware")

    args = parser.parse_args()
    logger.setLevel(args.verbose)
    ch.setLevel(args.verbose)

    args.func(args)
