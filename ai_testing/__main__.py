import os
import sys

os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

if len(sys.argv) > 1:
    from .cli import cli
    cli()
else:
    from .interactive import main
    main()
