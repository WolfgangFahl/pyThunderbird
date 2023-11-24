"""
Created on 2023-11-23

@author: wf
"""
from ngwidgets.cmd import WebserverCmd
from thunderbird.tb_webserver import ThunderbirdWebserver
from thunderbird.mail import Mail
import sys
from argparse import ArgumentParser

class ThunderbirdMailCmd(WebserverCmd):
    """
    command line access to pyThunderbird
    """

    def getArgParser(self,description:str,version_msg)->ArgumentParser:
        """
        override the default argparser call
        """        
        parser=super().getArgParser(description, version_msg) 
        parser.add_argument('-u','--user',type=str,help="id of the user")       
        parser.add_argument('-m','--mailid',type=str,help="id of the mail to retrieve")
        parser.add_argument('-ul','--user-list', default=[], nargs='+')
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
        if args.user is None or args.mailid is None:
            self.parser.print_help()
            return False
        else:
            # Creating a Mail object with the provided arguments
            mail = Mail(user=args.user, mailid=args.mailid, debug=args.debug)
            if mail.found:
                print(mail.msg)
                return True
            else:
                print("not found")
    
def main(argv:list=None):
    """
    main call
    """
    cmd=ThunderbirdMailCmd(config=ThunderbirdWebserver.get_config(),webserver_cls=ThunderbirdWebserver)
    exit_code=cmd.cmd_main(argv)
    return exit_code
        
DEBUG = 0
if __name__ == "__main__":
    if DEBUG:
        sys.argv.append("-d")
    sys.exit(main())
