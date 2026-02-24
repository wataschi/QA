import sys

if len(sys.argv) > 1:
    from .cli import cli
    cli()
else:
    from .interactive import main
    main()
