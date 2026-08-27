#include "contiki.h"
#include "coap-engine.h"
#include "dev/leds.h"
#include "os/sys/log.h"
#include "sys/etimer.h"
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#define LOG_MODULE "Actuator Node"
#define LOG_LEVEL LOG_LEVEL_INFO
#define SENSOR_NAME "anode_0"

PROCESS(led_blink_process,"led blink");
PROCESS(actuator_node, "Actuator Node");
AUTOSTART_PROCESSES(&actuator_node,&led_blink_process);

//Global variables
static bool pump_active=false;
static bool alarm_active=false;
extern coap_resource_t pump_resource;
extern coap_resource_t alarm_resource;

static void res_alarm_get_handler(coap_message_t *request, coap_message_t *response,uint8_t *buffer, uint16_t preferred_size, int32_t *offset){
    char msg[32];
    int len = snprintf((char *)buffer, preferred_size,"{\"alarm\": \"%s\"}",alarm_active?"ON":"OFF");
    coap_set_header_content_format(response, TEXT_PLAIN);
    coap_set_payload(response, buffer, len);
}
static void res_alarm_put_handler(coap_message_t *request, coap_message_t *response, uint8_t *buffer, uint16_t preferred_size, int32_t *offset) {
    const uint8_t *payload = NULL;
    int len = coap_get_payload(request, &payload);

    if(len > 0) {
        if(strncmp((const char *)payload, "1", 1)==0){
            if(alarm_active==false){
                alarm_active = true;
		leds_off(LEDS_GREEN);
                leds_on(LEDS_RED);
                LOG_INFO("[ACTUATOR] alarm activated\n");
                coap_set_status_code(response, CHANGED_2_04);
            }
        } else if(strncmp((const char *)payload, "0", 1)==0) {
            if(alarm_active==true){
                alarm_active = false;
                leds_off(LEDS_RED);
                leds_on(LEDS_GREEN);
                LOG_INFO("[ACTUATOR] alarm deactivated\n");
                coap_set_status_code(response, CHANGED_2_04);
            }
            
        } else {
            coap_set_status_code(response, BAD_REQUEST_4_00);
        }
    } else {
        coap_set_status_code(response, BAD_REQUEST_4_00);
    }
}
static void res_pump_get_handler(coap_message_t *request, coap_message_t *response,uint8_t *buffer, uint16_t preferred_size, int32_t *offset){
    char msg[32];
    int len = snprintf((char *)buffer, preferred_size,"{\"pump\": \"%s\"}",pump_active?"ON":"OFF");
    coap_set_header_content_format(response, TEXT_PLAIN);
    coap_set_payload(response, buffer,len);
}
static void res_pump_put_handler(coap_message_t *request, coap_message_t *response, uint8_t *buffer, uint16_t preferred_size, int32_t *offset) {
    const uint8_t *payload = NULL;
    int len = coap_get_payload(request, &payload);

    if(len > 0) {
        if(strncmp((const char *)payload, "1", 1)==0){
            if(pump_active==false){
                pump_active=true;
                process_poll(&led_blink_process);
                LOG_INFO("[ACTUATOR] pump activated\n");
                coap_set_status_code(response, CHANGED_2_04);
            }
        } else if(strncmp((const char *)payload, "0", 1)==0) {
            if(pump_active==true){
                pump_active = false;
                leds_single_on(LEDS_YELLOW);
                LOG_INFO("[ACTUATOR] pump deactivated\n");
                coap_set_status_code(response, CHANGED_2_04);
            }
            
        } else {
            coap_set_status_code(response, BAD_REQUEST_4_00);
        }
    } else {
        coap_set_status_code(response, BAD_REQUEST_4_00);
    }
}


RESOURCE(alarm_resource,
         "title=\"Alarm\";rt=\"Control\"",
         res_alarm_get_handler,
         NULL,
         res_alarm_put_handler,
         NULL);
RESOURCE(pump_resource,
         "title=\"Pump\";rt=\"Control\"",
         res_pump_get_handler,
         NULL,
         res_pump_put_handler,
         NULL);
PROCESS_THREAD(led_blink_process,ev,data){
    static struct etimer timer;
    PROCESS_BEGIN();
    leds_single_on(LEDS_YELLOW);
    while(1){
        if(pump_active){
            etimer_set(&timer, CLOCK_SECOND / 2);
            PROCESS_WAIT_EVENT_UNTIL(etimer_expired(&timer));
            if(pump_active) {
                leds_single_toggle(LEDS_YELLOW);
            }
        }
        else{
            PROCESS_YIELD();
        }
    }
    PROCESS_END();
}

PROCESS_THREAD(actuator_node,ev,data){
    PROCESS_BEGIN();
    LOG_INFO("actuator node starting");
    leds_on(LEDS_GREEN);
    coap_activate_resource(&alarm_resource,"alarm");
    coap_activate_resource(&pump_resource,"pump");
    while(1){
        PROCESS_YIELD();

    }
    PROCESS_END();
}


