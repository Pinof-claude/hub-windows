import os
import sys

if __name__ == "__main__":
    out = os.environ.get("HUB_SELFTEST")
    if out:  # vérif CI : dépendances embarquées dans l'exe (résultat écrit dans un fichier)
        try:
            import ctranslate2  # noqa: F401
            import faster_whisper  # noqa: F401
            import keyring.backends.Windows  # noqa: F401
            import sounddevice  # noqa: F401
            from hub.app import MainWindow  # noqa: F401
            msg, code = "OK", 0
        except BaseException:
            import traceback
            msg, code = traceback.format_exc(), 1
        with open(out, "w", encoding="utf-8") as f:
            f.write(msg)
        sys.exit(code)
    from hub.app import main
    main()
