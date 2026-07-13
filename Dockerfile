FROM gcc:latest

WORKDIR /app

# Copy everything from the root folder
COPY . .

# Compile main.cpp
RUN g++ -O3 main.cpp -o main

CMD ["./main"]
