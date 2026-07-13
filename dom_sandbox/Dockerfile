# Use a clean base image with a C++ compiler
FROM gcc:latest

WORKDIR /app

# Copy the entire parent directory contents into the container
COPY . .

# Compile the main.cpp file that sits in your root directory
RUN g++ -O3 main.cpp -o main

# Run the compiled binary
CMD ["./main"]
