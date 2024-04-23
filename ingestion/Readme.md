### How to index a repo
The repo must be git repo, since I use a git walker instead of a file system
1. Create empty folders for the repo, qdrant and quickwit data from the project root 
   1. `mkdir -p data/qdrant/data qwdata repo`
2. git clone the repo you want to index inside the `repo` folder in the root of the project. 
   1. `cd repo`
   2. `git clone https://github.com/BloopAI/bloop.git`
   3. `cd ..`
3. Currently the system only indexes the main branch 
4. The docker-compose file runs both qdrant and quickwit to index the content.
5. Open `docker-compose.yml` and set the env variables 
   1. environment:
      - REPO_SUBFOLDER=<Cloned Git repo named inside ./repo folder>
      - REPO_NAME=<Any identifier for the repo>
   2. Example:
    environment:
      - REPO_SUBFOLDER=bloop
      - REPO_NAME=bloop-ai
6. docker-compose up -d --build
7. docker logs -f --tail 10  retx-rust-app-1 to tail the logs
8. If you don't want to run the indexing, just want to spin up qdrant and tantivy on the data folder for inference, just run `docker-compose up qdrant quickwit`.
