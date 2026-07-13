FROM gcc:latest

WORKDIR /app

# Install the required JSON library
RUN apt-get update && apt-get install -y nlohmann-json3-dev

# Copy everything from the root folder
COPY . .

# Compile main.cpp
RUN g++ -O3 main.cpp -o main

CMD ["./main"]
