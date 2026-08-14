#ifndef PROJECT_CONF_H_
#define PROJECT_CONF_H_

/* --- CONFIGURAZIONE SPECIFICA PER NRF52840 DONGLE --- */

/* 1. Abilita il supporto USB nativo nel kernel nRF52 */
#define USB_SERIAL_CONF_ENABLE      1

/* 2. Forza il protocollo SLIP (usato da tunslip6) a passare via USB */
#undef SLIP_ARCH_CONF_USB
#define SLIP_ARCH_CONF_USB          1

/* 3. Configurazione Border Router e Webserver */
#ifndef BORDER_ROUTER_CONF_WEBSERVER
#define BORDER_ROUTER_CONF_WEBSERVER 1
#endif

#if BORDER_ROUTER_CONF_WEBSERVER
#define UIP_CONF_TCP 1
#endif

/* 4. Aumenta i log per vedere cosa succede durante il debug */
#define LOG_CONF_LEVEL_RPL                         LOG_LEVEL_DBG
#define LOG_CONF_LEVEL_TCPIP                       LOG_LEVEL_DBG
#define SLIP_CONF_LOG_LEVEL                        LOG_LEVEL_DBG

#endif /* PROJECT_CONF_H_ */