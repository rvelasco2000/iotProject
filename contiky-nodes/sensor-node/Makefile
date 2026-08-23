CONTIKI_PROJECT = sensor-node
all: $(CONTIKI_PROJECT)

CONTIKI = /home/riccardo/contiki-ng
CFLAGS += -DCOAP_MAX_CHUNK_SIZE=128
include $(CONTIKI)/Makefile.dir-variables
MODULES += $(CONTIKI_NG_APP_LAYER_DIR)/coap
MODULES_REL += /home/riccardo/contiki-ng/examples/newIotProject/venv/lib/python3.12/site-packages/emlearn
TARGET_LIBFILES += -lm
INC += /home/riccardo/contiki-ng/examples/newIotProject/venv/lib/python3.12/site-packages/emlearn
include $(CONTIKI)/Makefile.include
