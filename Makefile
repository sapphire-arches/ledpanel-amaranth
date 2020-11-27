PYTHON_SOURCES = $(wildcard *.py)
YOSYS_INCLUDE := $(shell yosys-config --datdir/include)
RAW_IMAGES := $(wildcard imgs/img*.raw)
IMAGES := $(patsubst %.raw,%.png,$(RAW_IMAGES))

CXXFLAGS ?=
CXXFLAGS += -std=c++14

all : waves.vcd

blinker.cpp : $(PYTHON_SOURCES)
	python main.py simulate

blinker_tb : blinker.cpp blinker_tb.cpp
	$(CXX) -Wall -O2 -Wpedantic $(CXXFLAGS) $(CFLAGS) -I$(YOSYS_INCLUDE) -o $@ blinker_tb.cpp

waves.vcd : blinker_tb
	./blinker_tb

%.png : %.raw
	convert -size 64x64 -depth 16 RGB:$<[0] -depth 8 $@

sequence.webm : $(IMAGES)
	ffmpeg -r 30 -f image2 -s 64x64 -i imgs/img%04d.png $@
