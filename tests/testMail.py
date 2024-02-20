"""
Created on 24.10.2020

@author: wf
"""
import mailbox
import os

from tests.base_thunderbird import BaseThunderbirdTest
from thunderbird.mail import Mail, Thunderbird


class TestMail(BaseThunderbirdTest):
    """
    Test Thunderbird mail access
    """

    def testCreateMailbox(self):
        """
        test creating a mailbox file
        """
        mboxFile = os.path.join(self.temp_dir, "testMailbox")
        mbox = mailbox.mbox(mboxFile)
        message = Mail.create_message(
            "john@doe.com", "mary@doe.com", "Hi Mary!", {"Subject": "Let's talk"}
        )
        mbox.add(message)
        mbox.close()

    def testIssue1(self):
        """
        test Mail access
        """
        mail = self.getMockedMail()
        self.assertEqual(mail.tb.user, self.mock_user)
        self.assertTrue(mail.msg is not None)
        subject = mail.msg.get("subject")
        if self.debug:
            print(subject)
        self.assertEqual(subject, "Wikidata Digest, Vol 107, Issue 2")
        pass

    def testIssue2(self):
        """
        see https://github.com/WolfgangFahl/pyThunderbird/issues/2
        Given a user id lookup the thunderbird profile
        """
        user = self.mock_user
        tb = Thunderbird.get(user)
        self.assertEqual(tb.user, user)

    def testIssue4(self):
        """
        https://github.com/WolfgangFahl/pyThunderbird/issues/4
        Folderpath mapping should work on all levels
        """
        folderURI = "mailbox://nobody@Local Folders/WF/Friends/Diverse"
        expectedSbdFolder = "/Mail/Local Folders/WF.sbd/Friends.sbd/Diverse"
        expectedFolder = "WF/Friends/Diverse"
        sbdFolder, folder = Mail.toSbdFolder(folderURI)
        self.assertEqual(sbdFolder, expectedSbdFolder)
        self.assertEqual(folder, expectedFolder)

    def testIssue8(self):
        """
        https://github.com/WolfgangFahl/pyThunderbird/issues/8
        make from and to headers clickable to allow replying to mail just displayed
        """
        mail = self.getMockedMail()
        self.assertEqual(
            mail.fromUrl,
            "<a href='mailto:wikidata-request@lists.wikimedia.org'>wikidata-request@lists.wikimedia.org</a>",
        )
        self.assertEqual(
            mail.toUrl,
            "<a href='mailto:wikidata@lists.wikimedia.org'>wikidata@lists.wikimedia.org</a>",
        )

    def testIssue10(self):
        """
        https://github.com/WolfgangFahl/pyThunderbird/issues/10
        display wikison notation for cut&paste into Semantic MediaWiki
        """
        mail = self.getMockedMail()
        wikison = mail.asWikiMarkup()
        expected = f"""{{{{mail
|user={self.mock_user}
|id=mailman.45.1601640003.19840.wikidata@lists.wikimedia.org
|from=wikidata-request@lists.wikimedia.org
|to=wikidata@lists.wikimedia.org
|subject=Wikidata Digest, Vol 107, Issue 2
|date=2020-10-03T12:00:03Z
}}}}"""
        if self.debug:
            print(wikison)
        self.assertEqual(expected, wikison)
        pass

    def testHeaderIssue(self):
        """
                 File "/hd/sengo/home/wf/source/python/pyThunderbird/thunderbird/mail.py", line 158, in __init__
            part.filename=str(make_header(decode_header(partname)))
          File "/usr/lib/python3.8/email/header.py", line 80, in decode_header
            if not ecre.search(header):
        TypeError: expected string or bytes-like object
        """
        if self.is_developer():
            tb = Thunderbird.get(self.user)
            debug = False
            mailid = "<61418716.20495.1635242774805@sb2-itd-337.admin.sb2>"
            mail = Mail(self.user, mailid=mailid, tb=tb, debug=debug)
            self.assertIsNotNone(mail.msg)
            if debug:
                print(mail)
            msgParts = mail.msgParts
            if debug:
                for i, msgPart in enumerate(msgParts):
                    print(f"{i}:{msgPart.filename}")

            self.assertTrue(msgParts[3].filename.startswith("Rü"))
