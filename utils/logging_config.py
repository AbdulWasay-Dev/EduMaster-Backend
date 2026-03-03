"""
Logging configuration for the application
"""
import logging
import sys
from pathlib import Path
from loguru import logger


def setup_logging(environment: str = "development"):
    """Setup application logging"""
    
    # Remove default loguru handler
    logger.remove()
    
    # Configure log format
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )
    
    # Console logging
    logger.add(
        sys.stdout,
        format=log_format,
        level="DEBUG" if environment == "development" else "INFO",
        colorize=True
    )
    
    # File logging for production
    if environment == "production":
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # Application logs
        logger.add(
            log_dir / "app.log",
            format=log_format,
            level="INFO",
            rotation="1 day",
            retention="30 days",
            compression="zip"
        )
        
        # Error logs
        logger.add(
            log_dir / "error.log",
            format=log_format,
            level="ERROR",
            rotation="1 day",
            retention="90 days",
            compression="zip"
        )
    
    # Configure standard library logging to use loguru
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            
            frame, depth = sys._getframe(6), 6
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
            
            logger.opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )
    
    # Intercept all standard library logging
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    
    # Set specific loggers
    for logger_name in ["uvicorn", "uvicorn.access", "fastapi"]:
        logging.getLogger(logger_name).handlers = [InterceptHandler()]
    
    logger.info(f"Logging configured for {environment} environment")
