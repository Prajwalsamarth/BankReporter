import os

CLIENT1_URL = os.environ.get(
    "CLIENT1_URL", "postgresql+psycopg://novabank:novabank@localhost:5433/novabank")
CLIENT2_URL = os.environ.get(
    "CLIENT2_URL", "mysql+pymysql://bfs:bfs@localhost:3307/bfs_core")
