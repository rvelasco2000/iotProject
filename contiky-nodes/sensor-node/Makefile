CONTIKI_PROJECT = sensor-node
all: $(CONTIKI_PROJECT)

CONTIKI = /home/riccardo/contiki-ng
CFLAGS += -DCOAP_MAX_CHUNK_SIZE=128
include $(CONTIKI)/Makefile.dir-variables
MODULES += $(CONTIKI_NG_APP_LAYER_DIR)/coap
include $(CONTIKI)/Makefile.include
