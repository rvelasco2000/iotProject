#include "contiki.h"
#include "cbor.h"
#include "dev/leds.h"
#include "coap-engine.h"
#include "sys/etimer.h"
#include "os/sys/log.h"
#include <stdio.h>
#include <stdlib.h>
#define LOG_MODULE "Sensor Node"
#define LOG_LEVEL LOG_LEVEL_INFO
#define SENSOR_NAME "snode_0"
#ifndef APPLICATION_CBOR
#define APPLICATION_CBOR 60
#endif
PROCESS(sensor_node, "Sensor Node");
AUTOSTART_PROCESSES(&sensor_node);


static clock_time_t interval=CLOCK_SECOND*30;
static int spo2=95;
static int respiration_rate=20;
static int heart_rate=70;
extern coap_resource_t vital_signs_resource;

static void res_get_handler(coap_message_t *request, coap_message_t *response, uint8_t *buffer, uint16_t preferred_size, int32_t *offset){
    cbor_writer_state_t state;
    
    cbor_init_writer(&state, buffer, preferred_size);
/*
    cbor_open_map(&state);
        cbor_write_text(&state, "s", 1);
        cbor_write_unsigned(&state, spo2);
        
        cbor_write_text(&state, "r", 1);
        cbor_write_unsigned(&state, respiration_rate);
        
        cbor_write_text(&state, "h", 1);
        cbor_write_unsigned(&state, heart_rate);
    cbor_close_map(&state);*/

    cbor_open_map(&state);
        //base name
        cbor_write_text(&state, "bn", strlen("bn"));
        cbor_write_text(&state, SENSOR_NAME, strlen(SENSOR_NAME));
        //base time
//        cbor_write_text(&state, "bt", strlen("bt"));
//        cbor_write_unsigned(&state, clock_seconds());
        //array of vital signs
        cbor_write_text(&state, "e", strlen("e"));
        cbor_open_array(&state);
            //spo2
            cbor_open_map(&state);
                cbor_write_text(&state, "n", strlen("n"));
                cbor_write_text(&state, "spo2", strlen("spo2"));
                cbor_write_text(&state, "u", strlen("u"));
                cbor_write_text(&state, "%", strlen("%"));
                cbor_write_text(&state, "v", strlen("v"));
                cbor_write_unsigned(&state, spo2);
            cbor_close_map(&state);
            //respiration rate
            cbor_open_map(&state);
                cbor_write_text(&state, "n", strlen("n"));
                cbor_write_text(&state, "resRate", strlen("resRate"));
                cbor_write_text(&state, "u", strlen("u"));
                cbor_write_text(&state, "b/min", strlen("b/min"));
                cbor_write_text(&state, "v", strlen("v"));
                cbor_write_unsigned(&state, respiration_rate);
            cbor_close_map(&state);
            //heart rate
            cbor_open_map(&state);
                cbor_write_text(&state, "n", strlen("n"));
                cbor_write_text(&state, "heartRate", strlen("heartRate"));
                cbor_write_text(&state, "u", strlen("u"));
                cbor_write_text(&state, "bpm", strlen("bpm"));
                cbor_write_text(&state, "v", strlen("v"));
                cbor_write_unsigned(&state, heart_rate);
            cbor_close_map(&state);
        cbor_close_array(&state);
    cbor_close_map(&state);

    size_t len = cbor_end_writer(&state);
    coap_set_header_content_format(response, APPLICATION_CBOR);
    coap_set_payload(response, buffer, len);
    LOG_INFO("i have send:spo2: %d, Respiration Rate: %d, Heart Rate: %d\n sended in %zu byte", spo2, respiration_rate, heart_rate,len);

} 

static void res_event_handler(void){
    spo2 = 85 + (rand() % 14);       
    respiration_rate = 12 + (rand() % 20);
    heart_rate = 60 + (rand() % 90);
    coap_notify_observers(&vital_signs_resource);
    LOG_INFO("spo2: %d, Respiration Rate: %d, Heart Rate: %d\n", spo2, respiration_rate, heart_rate);
}
EVENT_RESOURCE(vital_signs_resource,
               "title=\"vital signs\";obs",
               res_get_handler,
               NULL,
               NULL,
               NULL,
               res_event_handler);
PROCESS_THREAD(sensor_node,ev,data){
        static struct etimer et;
        PROCESS_BEGIN();
        coap_activate_resource(&vital_signs_resource, "vital_signs");
        etimer_set(&et, interval);
	leds_on(LEDS_GREEN);
        while(1){
            PROCESS_WAIT_EVENT_UNTIL(etimer_expired(&et));
            vital_signs_resource.trigger();
            etimer_reset(&et);
            //res_event_handler();
            LOG_INFO("Sensor Node is running\n");
        }
    PROCESS_END();
}
