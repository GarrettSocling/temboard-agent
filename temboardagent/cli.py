from multiprocessing import Process, Queue
import sys
import signal

from .sharedmemory import Commands, Sessions
from .async import Scheduler
from .options import temboardOptions
from .configuration import Configuration
from .errors import ConfigurationError
from .logger import get_logger, set_logger_name
from .daemon import (
    daemonize,
    httpd_sigterm_handler,
    set_global_scheduler,
    httpd_sighup_handler,
)
from .httpd import httpd_run
from .pluginsmgmt import load_plugins_configurations
from .queue import purge_queue_dir


def main():
    optparser = temboardOptions(description="temBoard agent.")
    (options, _) = optparser.parse_args()

    # Load configuration from the configuration file.
    try:
        config = Configuration(options.configfile)
        set_logger_name("temboard-agent")
        logger = get_logger(config)
        logger.info("Starting main process.")
    except (ConfigurationError, ImportError) as e:
        try:
            logger.error(str(e))
        except Exception:
            pass
        sys.stderr.write("FATAL: %s\n" % str(e))
        exit(1)

    # Run temboard-agent as a background daemon.
    if (options.daemon):
        daemonize(options.pidfile)

    config.plugins = load_plugins_configurations(config)

    # Purge all data queues at start time excepting metrics & notifications.
    purge_queue_dir(config.temboard['home'],
                    ['metrics.q', 'notifications.q', 'notifications_last_10.q']
                    )

    # Creation of the command list (max 100).
    commands = Commands(100)
    # Creation of the session list (max 100).
    sessions = Sessions(100)
    # Command queue creation.
    queue_in = Queue()

    # Start the command scheduler process.
    scheduler = Process(target=Scheduler,
                        args=(commands, queue_in, config, sessions))
    scheduler.start()

    # Let's store scheduler reference in a global var.
    set_global_scheduler(scheduler)
    # Add signal handlers on SIGTERM and SIGHUP.
    signal.signal(signal.SIGTERM, httpd_sigterm_handler)
    signal.signal(signal.SIGHUP, httpd_sighup_handler)

    # Serve HTTPS forever.
    httpd_run(commands, queue_in, config, sessions)

    # Join command scheduler process on http server process exit.
    scheduler.join()