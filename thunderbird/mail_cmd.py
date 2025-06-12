"""
Created on 2023-11-23

@author: wf
"""
import sys
from argparse import ArgumentParser

from ngwidgets.cmd import WebserverCmd

from thunderbird.mail import Mail, Thunderbird
from thunderbird.tb_webserver import ThunderbirdWebserver


class ThunderbirdMailCmd(WebserverCmd):
    """
    command line access to pyThunderbird
    """

    def getArgParser(self, description: str, version_msg) -> ArgumentParser:
        """
        override the default argparser call
        """
        parser = super().getArgParser(description, version_msg)
        parser.add_argument("-u", "--user", type=str, help="id of the user")
        parser.add_argument(
            "-m", "--mailid", type=str, help="id of the mail to retrieve"
        )
        parser.add_argument("-ul", "--user-list", default=[], nargs="+")
        parser.add_argument(
            "-ci",
            "--create-index",
            action="store_true",
            help="create an alternative index for the given users's Thunderbird mailarchive",
        )
        parser.add_argument(
            "-cil",
            "--create-index-list",
            default=[],
            nargs="+",
            help="create an alternative index for the given list of relative mailbox paths",
        )
        parser.add_argument(
            "-ml", "--mailid-like",
            help="SQL LIKE-style wildcard search for matching mail IDs"
        )
        parser.add_argument(
            "-f",
            "--force",
            action="store_true",
            help="force the creation of a new index even if one already exists",
        )
        parser.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            help="show verbose infos e.g. on startup [default: %(default)s]",
        )
        return parser

    def handle_args(self) -> bool:
        """
        Handles command line arguments.

        This method processes the command line arguments provided to the script.
        It checks for the presence of required arguments and initializes the Mail object
        if the necessary arguments are provided.

        Returns:
            bool: True if the arguments are processed successfully, False otherwise.
        """
        # Calling the superclass constructor or method, if needed
        super().handle_args()

        args = self.args

        # Check if both user and id arguments are provided
        if args.user is None:
            if args.mailid is None and not args.create_index:
                self.parser.print_help()
                return False
        elif args.create_index:
            tb = Thunderbird.get(args.user)
            indexing_state = tb.create_or_update_index(force_create=args.force)
            indexing_state.show_index_report(verbose=args.verbose)
        elif args.create_index_list:
            tb = Thunderbird.get(args.user)
            indexing_state = tb.create_or_update_index(
                force_create=args.force, relative_paths=args.create_index_list
            )
            indexing_state.show_index_report(verbose=args.verbose)
        elif args.mailid:
            # Creating a Mail object with the provided arguments
            mail = Mail(user=args.user, mailid=args.mailid, debug=args.debug)
            if mail.found:
                print(mail.msg)
                return True
            else:
                msg = f"mail with id {args.mailid} for user {args.user} not found"
                print(msg, files=sys.stderr)
                self.exit_code = 1
        elif args.mailid_like:
            tb = Thunderbird.get(args.user)
            records = tb.search_mailid_like(f"%{args.mailid_like}%")
            if records:
                for record in records:
                    line=""
                    delim=""
                    for key, value in record.items():
                        line+=f"{delim}{key}={value}"
                        delim="📂" if delim=="" else "|"
                    print (line)
                return True
            else:
                msg = f"❌ no mails matching '{args.mailid_like}' for user {args.user}"
                print(msg, file=sys.stderr)
                self.exit_code = 1


def main(argv: list = None):
    """
    main call
    """
    cmd = ThunderbirdMailCmd(
        config=ThunderbirdWebserver.get_config(), webserver_cls=ThunderbirdWebserver
    )
    exit_code = cmd.cmd_main(argv)
    return exit_code


DEBUG = 0
if __name__ == "__main__":
    if DEBUG:
        sys.argv.append("-d")
    sys.exit(main())
