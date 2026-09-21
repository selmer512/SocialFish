import sys

import colorama


def _console_print(value=""):
    try:
        print(value)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        safe_value = str(value).encode(encoding, errors="replace").decode(encoding)
        sys.stdout.write(safe_value + "\n")

def head():
    _console_print(colorama.Style.BRIGHT)
    _console_print(colorama.Fore.CYAN + '''
                          '
                        '   '  UNDEADSEC | t.me/UndeadSec 
                      '       '  youtube.com/c/UndeadSec - BRAZIL
                 .  '  .        '                        '
             '             '      '                   '   '
  ███████ ████████ ███████ ██ ███████ ██       ███████ ██ ███████ ██   ██ 
  ██      ██    ██ ██      ██ ██   ██ ██       ██      ██ ██      ██   ██ 
  ███████ ██    ██ ██      ██ ███████ ██       █████   ██ ███████ ███████ 
       ██ ██    ██ ██      ██ ██   ██ ██       ██      ██      ██ ██   ██ 
  ███████ ████████ ███████ ██ ██   ██ ███████  ██      ██ ███████ ██   ██ 
      .    '   '....'               ..'.      ' .
         '  .                     .     '          '     '  v3.0Nepture
               '  .  .  .  .  . '.    .'              '  .
                   '         '    '. '      Twitter: https://twitter.com/UndeadSec
                     '       '      '       Site: https://www.undeadsec.com
                       ' .  '
                           ''')
    _console_print(colorama.Fore.GREEN + 'Go to http://0.0.0.0:5000/neptune to start')
