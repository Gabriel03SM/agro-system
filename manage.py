#!/usr/bin/env python
import os
import sys


def main():
    configuracao = "config.test_settings" if len(sys.argv) > 1 and sys.argv[1] == "test" else "config.settings"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", configuracao)
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
