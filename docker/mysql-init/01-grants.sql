-- bfs may drop/recreate its own database (generator --reset) and own the lending_rpt views database (Part 2).
GRANT ALL PRIVILEGES ON `bfs_core`.* TO 'bfs'@'%';
GRANT ALL PRIVILEGES ON `lending_rpt`.* TO 'bfs'@'%';
GRANT ALL PRIVILEGES ON `lending_rpt_eval`.* TO 'bfs'@'%';
FLUSH PRIVILEGES;
