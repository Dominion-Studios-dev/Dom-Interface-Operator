FROM gcc:latest
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libasio-dev \
    libboost-dev \
    nlohmann-json3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*
COPY . .
RUN g++ -O3 -std=c++17 main.cpp -lpthread -o main && rm -f *.o
ENV PORT=7860
EXPOSE ${PORT}
CMD ["./main"]