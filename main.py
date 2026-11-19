import os
import sys

if __name__ == "__main__":
    if os.environ.get("HUB_SELFTEST"):  # vérif CI : dépendances embarquées dans l'exe
        import ctranslate2  # noqa: F401
        import faster_whisper  # noqa: F401
        import keyring.backends.Windows  # noqa: F401
        import sounddevice  # noqa: F401
        from hub.app import MainWindow  # noqa: F401
        print("SELFTEST OK")
        sys.exit(0)
    from hub.app import main
    main()
