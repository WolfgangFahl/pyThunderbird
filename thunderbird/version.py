"""
Created on 2023-11-23

@author: wf
"""
from dataclasses import dataclass

import thunderbird


@dataclass
class Version(object):
    """
    Version handling for pyThunderbird
    """

    name = "pyThunderbird"
    version = thunderbird.__version__
    description = "python based access to Thunderbird mail"
    date = "2021-09-23"
    updated = "2025-06-12"

    authors = "Wolfgang Fahl"

    doc_url = "https://wiki.bitplan.com/index.php/pyThunderbird"
    chat_url = "https://github.com/WolfgangFahl/pyThunderbird/discussions"
    cm_url = "https://github.com/WolfgangFahl/pyThunderbird"

    license = f"""Copyright 2020-2023 contributors. All rights reserved.

  Licensed under the Apache License 2.0
  http://www.apache.org/licenses/LICENSE-2.0

  Distributed on an "AS IS" basis without warranties
  or conditions of any kind, either express or implied."""

    longDescription = f"""{name} version {version}
{description}

  Created by {authors} on {date} last updated {updated}"""
