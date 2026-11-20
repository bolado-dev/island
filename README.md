<p align="center">
  <img src="docs/logo.png" alt="" width="128">
</p>

<h1 align="center">island</h1>

<p align="center">
  Un notch para bspwm, con la mecánica del Dynamic Island: se repliega
  cuando no hace falta y se despliega con lo que está pasando.
</p>

<p align="center">
  <img alt="estado" src="https://img.shields.io/badge/estado-alpha-orange">
  <img alt="licencia" src="https://img.shields.io/badge/licencia-MIT-blue">
  <img alt="python" src="https://img.shields.io/badge/python-3.9%2B-3776ab">
  <img alt="x11" src="https://img.shields.io/badge/X11-bspwm-333">
</p>

<p align="center">
  <img src="docs/hero.png" alt="El notch en reposo sobre el escritorio: reloj, fecha, indicador de escritorios y estado del sistema, en una pastilla negra colgando del borde superior" width="900">
</p>

---

## Por qué

Una barra de estado en un gestor de mosaico ocupa una franja a todo lo ancho
de la pantalla para enseñarte, casi siempre, nada. La mía eran 898 píxeles de
los que solo el 10% tenía contenido; el resto era negro esperando a que
pasara algo.

El notch del MacBook resuelve eso de una forma que me parece honesta: el
hueco ya está perdido por el hardware, así que lo usan para lo que importa y
el resto del tiempo no está. El Dynamic Island da el paso siguiente — la
misma pieza cambia de tamaño según lo que tenga que decirte.

island es eso para bspwm. En reposo es una pastilla pequeña pegada al borde.
Cuando llega una notificación se abre en tarjeta; cuando tocas el volumen se
estira en una píldora con el deslizador; cuando levantas una VPN se queda con
la IP hasta que la bajas.

**Por qué no es una configuración de polybar.** Lo intenté primero. Polybar
dibuja texto y repinta la barra entera en cada actualización: se puede
falsear una animación imprimiendo fotogramas, pero son redibujados X11
completos, el ancho salta por anchos de carácter y a 20-30 fps ya se ve a
tirones. Además las esquinas redondas tienen que salir de glifos de una
fuente, y los de Nerd Fonts no son semicírculos de verdad — medidos, su
relación ancho/alto es 0.467 en vez de 0.5.

Aquí la ventana es un lienzo transparente y la forma se dibuja con cairo. Sale
gratis lo que allí costaba: geometría exacta, 60 fps reales y animaciones con
física.

## Qué hace

<p align="center">
  <img src="docs/workspaces.gif" alt="Al cambiar de escritorio el notch baja solo, con la píldora azul ya colocada en el escritorio nuevo, y vuelve a replegarse" width="760">
</p>

**Se repliega.** `top_padding` a 0: las ventanas usan la pantalla entera y el
notch deja asomar 3 píxeles. Baja al acercar el ratón al borde superior, y
también solo cuando hay algo que enseñar — un cambio de escritorio, una
notificación, el cargador enchufado.

**Escritorios.** Una pista de segmentos con la píldora del activo. La píldora
no viaja entre huecos: nace como un punto en el escritorio nuevo y se estira
hasta su tamaño mientras el anterior hace el gesto al revés, encogiendo y
apagándose. Verla cruzar por encima de los escritorios de en medio arrastraba
la mirada por un camino que no importa, y el cambio lo acabas de pulsar tú.

Un solo muelle gobierna la entrada y la salida, así que no pueden
desacompasarse. Se ajusta con `WS_POP` y `SP_POP_*` en `theme.py`, y
`WS_ANIM` devuelve el deslizamiento si lo prefieres.

Clic izquierdo salta a ese escritorio; clic derecho abre los ajustes del
mosaico (monocle, equilibrar, rotar, separación, no molestar).

<p align="center">
  <img src="docs/notification.gif" alt="Una notificación hace que el notch se despliegue en tarjeta con el icono de la aplicación, el título y el cuerpo, y luego vuelva a replegarse" width="760">
</p>

**Notificaciones.** Entran por una regla de dunst, que deja de pintar su
propia burbuja y se las pasa al notch. El icono sale del tema de iconos o del
que mande la aplicación; el marcado HTML del cuerpo se limpia antes de
pintarlo.

Para las notificaciones web hay reglas en `apps.json`: Chrome manda todas las
suyas como «Google Chrome», así que se cruzan el nombre, el título, el cuerpo
y la URL de origen contra una lista de patrones. Si casa, se baja el favicon
**del propio sitio** — no de un servicio de terceros, que sabría qué páginas
te escriben.

<table>
  <tr>
    <td><img src="docs/resplandor-notificacion.png" alt="Una notificación de Telegram con un halo azul cian alrededor del notch, del color del icono"></td>
  </tr>
  <tr>
    <td><img src="docs/resplandor-dictado.png" alt="La tarjeta de dictado escuchando, con un halo naranja del color del logo de Claude"></td>
  </tr>
</table>

**Y se enciende del color de quien avisa.** Un medio radial estirado, pegado
al canto de **abajo** y por dentro del propio cuerpo. Abajo y no arriba
porque arriba el notch está pegado al borde de la pantalla y la luz muere
contra un canto recto; abajo monta sobre las dos esquinas redondeadas, que es
la única forma libre que tiene, y se lee como luz del propio cuerpo. Dentro y
no fuera a
propósito: así se ve siempre igual, sin depender de qué fondo de escritorio
tengas detrás. Va debajo del contenido, así que el texto se lee exactamente
igual que antes.

El color sale del icono de verdad —el favicon del servicio, la carátula del
disco—, no de una lista de colores por aplicación: una lista hay que
mantenerla y se queda corta con la primera app que no esté. Lo único que lleva
tabla son los logos de las IA del dictado, porque sus SVG son siluetas de un
color plano y no hay nada que sacarles. Y si no hay icono —un `notify-send`
pelado no manda ninguno— se usa el color con el que se dibuja la campana, que
es lo que estás viendo igualmente.

Sacarlo no es la media de los píxeles: la media de un logo sobre fondo blanco
es gris claro, y un resplandor gris no es un resplandor. Cada píxel pesa lo
**saturado** que está —que es lo que identifica a una marca—, se tiran los
grises y lo casi negro, y el resultado se sube a un tono vivo. Lo que se pinta
no es el icono: es la luz que echaría.

La elipse se define en **fracciones de la isla**, no en píxeles, así que tiene
la misma forma en una píldora de 300 y en una tarjeta de 900 y una sola
textura de 128x64 por color sirve para las dos: se estira al pintarla, y
estirarla es justo lo que la hace un medio radial estirado. Medido: 0,16 ms
por fotograma, frente a 0,9 pintando el degradado de verdad cada vez.

La caída va repartida en **cinco paradas** y la elipse es casi tan ancha como
la isla. Con dos o tres paradas y un radio corto, el centro se queda como un
punto brillante y el resto cae de golpe: se ve *dónde* está el foco, que es
justo lo contrario de difuminado. Así no hay un punto, hay una zona.

Brillan las **tarjetas**: avisos, dictado, música, capturas, el cargador al
enchufarlo y las cuentas atrás al cumplirse. Los demás paneles no: un panel no
se anuncia, lo has pedido.

<p align="center">
  <img src="docs/resplandor-lanzador.png" alt="El lanzador con Firefox seleccionado y un resplandor naranja, del color de su icono, saliendo del canto de abajo" width="520">
</p>

**El lanzador es la excepción**, y es donde más se nota: toma el color del
resultado que tienes **señalado** y cambia al moverte por la lista, así que el
notch se tiñe del programa que vas a abrir antes de abrirlo. Es la misma regla
de siempre —el color de lo que estás viendo—, solo que aquí lo que estás
viendo cambia con las flechas. En un panel alto la luz no se estira de canto
a canto: tiene tope en píxeles, para que siga siendo una luz que entra por uno
de ellos y no un tinte.

Entre dos avisos seguidos —o entre dos resultados— el color **viaja** en vez
de saltar, y se enciende y se apaga con muelle: un halo que aparece de golpe
se lee como un parpadeo.

**Y respira.** Un latido lento de 2,6 s, con coseno y no con rampa: una rampa
que vuelve de golpe al principio se ve como un corte por muy lenta que sea. La
luz baja un 38% en lo más bajo del ciclo y crece un pelo al encenderse, como
el aire. Late lo que **avisa**: un aviso, el dictado, una captura, el cargador,
una cuenta cumplida. El lanzador no, porque una luz parpadeando al lado del
texto que estás escribiendo es lo contrario de ayudar; y la música tampoco,
porque esa tarjeta se queda mientras suene el disco y algo que respira durante
cuarenta minutos deja de ser un latido.

El latido **no corre a 120 Hz**. Es una rampa de opacidad, no un movimiento:
si no se mueve nada más en la isla, el bucle sigue vivo pero solo repinta 30
veces por segundo, que se ve exactamente igual. Medido: 3% de un núcleo
mientras una tarjeta respira, y 0 en reposo.

Hay además un halo que se derrama **fuera**, sobre el escritorio, con la
silueta del notch desenfocada. Viene apagado (`GLOW_HALO` en `theme.py`)
porque los dos a la vez se pisan. Se genera una vez a 1/8 de tamaño con veinte
siluetas concéntricas y se estira al pintarlo: el estirado hace de
desenfoque, que cairo no tiene. `GLOW` apaga los dos.

<table>
  <tr>
    <td><img src="docs/panel-volume.png" alt="Panel de volumen: icono de altavoz, deslizador arrastrable y porcentaje, todo en una fila"></td>
    <td><img src="docs/panel-power.png" alt="Panel de energía: estado de la batería y cuatro botones de perfil, con el activo resaltado en azul"></td>
  </tr>
  <tr>
    <td><img src="docs/panel-wifi.png" alt="Panel de wifi: la IP local junto al título y la lista de redes con indicador de conectada, candado y cobertura"></td>
    <td><img src="docs/panel-calendar.png" alt="Calendario del mes con el día de hoy marcado en azul y flechas para cambiar de mes"></td>
  </tr>
</table>

**Paneles.** Cada icono de estado abre el suyo: volumen con deslizador real,
perfiles de energía, redes wifi —con entrada de contraseña dentro del propio
notch— y el reloj. El botón de encendido abre el menú de sesión.

<table>
  <tr>
    <td><img src="docs/panel-crono.png" alt="Cronómetro: las cifras grandes de los segundos y, a media altura, las centésimas corriendo"></td>
    <td><img src="docs/panel-temporizador.png" alt="Temporizador: el tiempo restante, una barra de progreso, los botones de menos un minuto, pausa, cancelar y más un minuto, y cinco atajos de minutos con el de 10 marcado"></td>
    <td><img src="docs/panel-pomodoro.png" alt="Pomodoro: la fase Trabajo con cuatro puntos de tanda, el tiempo restante, la barra y los botones de pausa, saltar fase y reiniciar"></td>
  </tr>
</table>

**El reloj tiene cuatro pestañas.** Calendario, cronómetro, temporizador y
pomodoro. Un reloj que solo enseña la fecha deja fuera justo lo que se le pide
a un reloj además de la hora: medir, contar hacia atrás y trabajar a tandas.

La barra de pestañas va **arriba**, y no es una preferencia. El notch cuelga
del borde de la pantalla: su canto de arriba no se mueve jamás y el de abajo
sube y baja con lo que mida cada pestaña —el calendario ocupa 440 px y el
cronómetro 300—. Con la barra abajo, pulsar «cronómetro» encogía el panel y se
llevaba la barra 140 px hacia arriba, fuera de donde acababas de pulsar; el
segundo clic caía en el escritorio y cerraba el panel. Arriba, las cuatro
están siempre en el mismo sitio. Y las cuatro miden lo mismo de ancho (el del
calendario, que es el más ancho), así que cambiar de pestaña solo mueve el
alto.

**Cronómetro.** Los segundos ruedan como el reloj de la barra; las centésimas,
no. Cambian cien veces por segundo, así que animarlas no se vería y
reconstruir el panel a ese ritmo sería medir todo el contenido con Pango cien
veces por segundo: se leen en vivo al dibujar, en un hueco de ancho fijo. Lo
que tiene ritmo de persona rueda; lo que corre, corre.

**Temporizador.** Cinco atajos de minutos —un clic y ya está contando—, ±1
minuto sin perder el ritmo y cancelar. El botón de cancelar borra la cuenta en
vez de rebobinarla: una cuenta atrás devuelta a su marca y parada no habría
forma de quitarla de en medio, y el notch seguiría enseñándola.

**Pomodoro.** 25 de trabajo, 5 de descanso y uno largo de 15 cada cuatro, que
son los números de Cirillo. La fase siguiente arranca sola: pararse a esperar
un clic convertiría el descanso en algo que administrar, y el pomodoro existe
para no tener que pensar en el reloj. El color dice en qué fase va —azul
trabajar, verde parar— y los puntos, por dónde va la tanda.

Mientras algo corre, el notch lo enseña **en reposo**, al lado de la hora, y
pulsarlo lleva a su pestaña. En pausa también sale, apagado: olvidarse de un
cronómetro parado es justo lo que ese indicador evita.

Nada de esto gasta con el notch replegado. La cifra solo se refresca si hay
algo que mirar —replegado no se dibuja ni una vez, y al asomar se pone al día
de golpe—, y el final de una cuenta no se vigila mirando el reloj cada
segundo, sino con un temporizador exacto que despierta una sola vez. Medido:
un temporizador de 25 minutos corriendo cuesta lo mismo que no tener ninguno.

Al acabar suena el aviso del sistema (`SONIDO*` en `config.py`) y baja una
tarjeta con «Repetir» y «Listo»: un temporizador que solo avisa en pantalla no
sirve de nada, porque lo pones justo para irte a hacer otra cosa.

También se maneja sin ratón, que es además como está probado:

```sh
island-send tiempo --target temp --value 1500    # 25 minutos
island-send tiempo --target crono --state play
island-send tiempo --target pomo --state skip
```

<p align="center">
  <img src="docs/launcher.png" alt="Lanzador: campo de búsqueda, resultado destacado en grande con su icono y tipo, y debajo la lista con el tipo de cada resultado alineado a la derecha" width="620">
</p>

<p align="center">
  <img src="docs/launcher.gif" alt="El lanzador con una búsqueda escrita; al volver a pulsar super y d se cierra y el notch se repliega" width="760">
</p>

**Lanzador.** Aplicaciones, ventanas abiertas, una calculadora, ejecución de
comandos, lo último que has copiado y las herramientas del propio notch, en
una sola lista ordenada por relevancia y por uso. Las ventanas
van primero a propósito: en un gestor de mosaico lo que sueles querer es
saltar a algo que ya tienes abierto, no abrir otra instancia.

Lo del notch está ahí porque un cronómetro **no es un `.desktop`**: buscarlo
por su nombre no encontraba nada, y el único sitio donde vivía era un icono
que hay que saber que existe. Escribiendo «cronómetro», «pomodoro», «emoji» o
«portapapeles» sale su acción, y el Intro no se limita a abrir el panel: lo
pone en marcha, porque quien escribe el nombre de un cronómetro quiere medir
algo, no mirar un cero parado.

Y una duración escrita se entiende como tal: «10 min», «90 s», «1 h» o
«temporizador 25» arrancan la cuenta atrás directamente. Pide unidad a
propósito — un «10» suelto es una cuenta de la calculadora o el principio de
un nombre, no diez minutos.

**El mismo atajo lo cierra.** `super + d` otra vez y se va, igual que
`super + .` y `super + v` con los suyos. Tiene miga: mientras un panel está
abierto tiene agarrado el teclado, así que sxhkd **no llega a ver** la
combinación y no puede volver a dispararla. La segunda pulsación le llega a la
isla como una tecla normal --por eso antes `super + d` escribía una `d` en la
búsqueda- y es ella quien decide cerrarse. La tecla de cada panel está en
`config.PANEL_TECLA`, y tiene que coincidir con tu `sxhkdrc` porque la isla no
puede preguntárselo a nadie.

La calculadora no usa `eval()`: recorre el árbol de sintaxis y rechaza
cualquier nodo que no sea aritmética. Un lanzador evaluando lo que tecleas
sería ejecutar código arbitrario.

El historial del portapapeles solo aparece **cuando escribes algo**: sin
búsqueda, lo que quieres es saltar a una ventana o abrir un programa, que es a
lo que se abre el lanzador el 95% de las veces. Y no toca el disco a
propósito: por el portapapeles pasan contraseñas, y lo que no se guarda no se
filtra.

<p align="center">
  <img src="docs/portapapeles.gif" alt="El panel del portapapeles con lo último copiado, cada línea con su tipo; al pulsar control y P la línea sube al principio con una chincheta azul, y al pulsar intro se pega en la ventana que había detrás" width="860">
</p>

**Y tiene panel propio en `super + v`**, como el de Windows: la lista de lo
último copiado, numerada, con las flechas para moverte y `⏎` para pegarlo **en
la ventana que tenías delante** --no en el portapapeles para que lo pegues tú-.
Escribir filtra. Es el mismo historial que ve el lanzador, así que no hay dos
listas que puedan discrepar.

**Cada línea dice qué es**: URL, correo, ruta, color, comando, código, número o
texto, con su glifo y su etiqueta en columna a la derecha. No se adivina el
programa ni el lenguaje --son miles-, se mira la forma, que es lo que no cambia.
Y lo que **es** código va en monoespaciada: en proporcional, la `l` y el `1` o la
`O` y el `0` se confunden justo en lo único que hay que leer con precisión. Un
párrafo de varias líneas no es código y sigue en proporcional.

Un color **se enseña**, no se lee: si lo copiado es un `#rrggbb` sale su muestra.
Y arriba va el contenido entero del seleccionado, hasta tres líneas, con su tipo,
su tamaño y cuándo lo copiaste: es la diferencia entre ver 58 caracteres y ver
lo que vas a pegar.

Los números son atajos --`3` pega el tercero, y solo sin búsqueda activa, que si
no escribir «3 cosas» en el filtro pegaría-, `⌦` olvida una entrada sin cerrar
el panel y **`^P` la fija**: lo fijado sube al principio, lleva chincheta y deja
de caerse cuando el historial se llena. Eso último es lo que lo hace útil para
lo que repites veinte veces al día.

Olvidar no toca el portapapeles del sistema: si borras justo lo último copiado
sigue estando a un Ctrl+V, lo que se tira es el recuerdo. Y fijar tampoco toca
el disco. Fijar es decir «esto lo voy a pegar varias veces», no «guárdame esto
para siempre», y por el portapapeles pasan contraseñas: lo que no se escribe no
se filtra.

Lo que no sale ahí son las imágenes: el historial es de texto. Después de una
captura, el portapapeles tiene un PNG y `xclip -o` devuelve bytes que no son
UTF-8; el sondeo se come esa excepción y sigue, así que la imagen se ignora sin
ensuciar la lista. Es además la única pieza de la isla que sondea, porque X no avisa de
un cambio de selección a quien no se registra con XFixes y eso significaba
meter un segundo bucle de eventos de X dentro de una aplicación GTK. Medido,
la alternativa tonta sale a 0,1% de un núcleo: un `xclip -o` son 3 ms, uno
cada tres segundos.

<p align="center">
  <img src="docs/emoji.gif" alt="Al pulsar super y punto el notch se despliega en una rejilla de emoji en color con una barra de categorías abajo; el tabulador y el ratón cambian de categoría, y al escribir fuego la barra desaparece y la rejilla se queda en una fila" width="760">
</p>

**Selector de emoji**, en `super + .` como el de Windows. Escribes, eliges y el
emoji aparece **en la ventana que tenías delante**, no en el portapapeles para
que lo pegues tú. Las flechas mueven y los que más usas salen los primeros.

**Las categorías van abajo**, como en el teclado de iOS: se pulsan, el tabulador
las recorre, y la actual se marca sola según dónde estés en la rejilla. El icono
de cada una es **un emoji de esa misma categoría** y no un glifo de Nerd Font:
la rejilla ya está hecha de emoji en color, y meter ahí iconos monocromos de
otra familia sería mezclar dos idiomas en un palmo.

Dos detalles que solo se ven usando esto. Al saltar a una categoría, su primera
fila queda **arriba del todo** y no pegada abajo: desplazar lo justo para que se
vea es lo que quieren las flechas, pero saltar a un sitio es empezar a mirar
ahí. Y la barra **desaparece al buscar**, porque los resultados salen de toda la
lista y mezclados, así que ahí las categorías ya no estructuran nada.

**Busca en castellano**, que es lo que uno escribe: «fuego» encuentra 🔥 y
«cohete» 🚀. Los nombres salen de [CLDR](https://github.com/unicode-org/cldr)
y los baja `fetch-icons.sh`; hacen falta sus dos ficheros, porque
`annotations` solo trae los emoji de un carácter y sin `annotationsDerived`
—la familia de cuatro, las banderas, los oficios— se queda en el 83%. También
busca por el nombre en inglés, porque media jerga de emoji se dice así. Sin
el fichero no se rompe nada: se busca solo en inglés, que es lo que trae el
sistema.

**La lista es la del sistema, no una copia.** `emoji-test.txt` (paquete
`unicode-data`) es la lista oficial del consorcio, con el orden y los grupos
ya decididos por ellos y pensados justo para una paleta de teclado. De los
3947 que trae se enseñan 1914: se quitan las variantes de tono de piel, que
multiplican por seis cada emoji de persona y dejarían la rejilla llena de la
misma mano repetida.

**La rejilla puede ser uniforme porque se midió.** A 30 píxeles, los 1914
emoji miden 37 × 36 **exactos** con Noto Color Emoji —banderas, teclas y
familias de cuatro incluidas—, así que la celda es fija y las columnas salen
rectas sin medir una por una.

**Y se filtra lo que la fuente no sepa dibujar**, porque los datos de Unicode
van por delante de las fuentes y un emoji sin glifo sale como un cuadro vacío.
No vale preguntar por los glifos desconocidos, que es lo que uno haría:
fontconfig tapa el hueco con otra fuente y Pango informa de cero. Lo que sí se
ve es el **ancho**: un emoji dibujado de verdad ocupa una casilla y una
secuencia que la fuente no conoce se descompone en sus piezas y ocupa el
doble exacto. Son 150 ms una vez, en un hilo mientras arranca el escritorio,
para que abrir el selector no espere nunca.

Un detalle que obligó a que los emoji no sean texto normal: **una fuente de
color ignora el color de origen de cairo, y con él el alfa**. Pidiendo
`rgba(1,1,1,0)` el emoji sale igual de opaco, así que con un `Text` corriente
se habría colado entero en mitad de los fundidos de la isla. Dibujarlo en un
grupo y volcarlo con `paint_with_alpha` sí funde.

El pegado es el mismo código que el del dictado (`sources.pegar`): las dos
cosas hacen exactamente lo mismo, dejar algo en la ventana que tenías
delante, y dos copias se habrían separado en cuanto una aprendiese algo.

<p align="center">
  <img src="docs/captura.gif" alt="Al pulsar el atajo el escritorio se atenua, una cruz sigue al cursor, se arrastra un rectángulo que enseña su tamaño en una pastilla, y al soltar baja el notch con la miniatura de lo capturado y tres botones" width="860">
</p>

**Capturas de pantalla.** `Print` selecciona una región, `ctrl + Print` coge la
pantalla entera y `alt + Print` la ventana enfocada. Baja el notch con **la
miniatura de verdad** de lo que acabas de capturar, el tamaño, y tres botones:
abrirla, abrir la carpeta o borrarla. Queda en `~/ScreenShots` y copiada al
portapapeles, porque una captura casi siempre es para pegarla en otro sitio.

Borrar ahí mismo es la razón de ser de la tarjeta: la mitad de las capturas se
hacen para mirarlas diez segundos, y si no tienes dónde tirarlas se quedan en
la carpeta para siempre.

**El notch se aparta antes de disparar.** Encadenar dos capturas es lo normal,
y la tarjeta de la primera sigue a la vista cuando disparas la segunda: saldría
en la foto. Se le pide que se repliegue y se espera a que lo haga. Eso obligó a
arreglar algo que venía de antes: **el repliegue solo se programaba al salir el
ratón o al cambiar de escritorio**, nunca al caducar lo que se estaba
enseñando, así que el notch se quedaba abajo hasta que lo rozabas.

**La miniatura la hace el ayudante, no la isla.** Medido aquí: sacarla del PNG
completo son 34 ms y sacarla de la miniatura ya hecha, 1. Lo que importa no es
el factor treinta, es que esos 34 ms caerían en el hilo de GTK --dos fotogramas
perdidos- justo en la animación de entrada de la tarjeta.

Y la miniatura no es un `Image` con otra foto dentro: ese es cuadrado, porque un
icono de aplicación y una carátula lo son. Una captura no, y meterla en un
cuadrado la deformaría o recortaría justo lo que te hizo capturarla. Manda el
alto, el ancho sale de la proporción y hay un tope por si capturas algo muy
alargado.

**El subtítulo tiene ancho fijo**, el del texto más largo que puede salir ahí.
Al señalar un botón, donde ponía el tamaño pone lo que hace ese botón --así la
etiqueta vive en un sitio y no en tres chips que ensancharían la tarjeta-, y sin
reservar el hueco la tarjeta se encogía al señalar: lo que se movía era justo el
botón que estabas a punto de pulsar.

<p align="center">
  <img src="docs/capture.png" alt="Tarjeta de captura: la miniatura de lo recién capturado, el tamaño en píxeles y tres botones redondos de abrir, carpeta y borrar" width="620">
</p>

**La selección es propia**, no la de otro programa. El escritorio se congela, se
atenúa, y lo que eliges se queda a brillo pleno: escuadras azules en las
esquinas, el tamaño en una pastilla negra con la misma tipografía del notch, y
una cruz tenue por el cursor antes de empezar. Arrastras y sueltas; `esc`, el
botón derecho o un clic sin arrastrar cancelan.

**Congela sin congelar X.** Lo primero que probé fue `scrot --select`, que no
pinta **nada** encima --solo cambia el cursor y traza una línea fina al
arrastrar-, así que al pulsar el atajo parecía que no había pasado nada. Y su
`--freeze` lo hace con `XGrabServer`: mientras eliges, ningún otro cliente de X
puede dibujar, y si el que captura se colgase, el escritorio entero se quedaría
tieso detrás.

Aquí es al revés: se saca una foto del escritorio --19 ms, y coincide con lo que
da scrot al 0,00%- y se enseña a pantalla completa. Lo que ves está quieto
porque es una foto, no porque el servidor esté bloqueado. De propina, la región
se recorta de **esa misma foto**, así que ni el velo ni el marco ni la etiqueta
pueden acabar dentro de la captura por mucho que se dibujen encima.

Es una ventana `POPUP` a propósito: una normal la gestionaría bspwm, la
colocaría en el mosaico y se vería el tirón. Y la captura de teclado se
**reintenta** 24 veces cada 25 ms, porque con `super + shift + s` --que dispara
al pulsar- sxhkd todavía tiene el teclado agarrado cuando esto arranca; al
primer intento el servidor contesta `ALREADY_GRABBED` y sin reintentar el
selector se cerraría solo sin decir nada. Mismo caso que el lanzador con
`super + d`.

La pantalla entera y la ventana siguen siendo `scrot`, que para eso no hace
falta interfaz ninguna. `CAPTURA_SELECTOR` en `config.py` devuelve la selección
a scrot si algún día hace falta.

`super + shift + s` hace lo mismo que `Print` a secas. Es un atajo de más a
propósito: es el que está en los dedos de tanto usarlo, y una tecla que ya sabes
pulsar vale más que una coherencia bonita.

**Reproducción.** Lo que suene por MPRIS aparece con carátula y controles.

<p align="center">
  <img src="docs/music.png" alt="Tarjeta de reproducción con carátula, título, artista y controles de anterior, pausa y siguiente" width="520">
</p>

**Avisa cuando la IA termina.** Te vas a otra ventana mientras Claude trabaja
y el notch baja a decirte que ha acabado, con su logo y lo que tardó. La señal
es el girador que las CLI de IA ponen delante del título del terminal: cuando
desaparece, han terminado. Vale para cualquiera que haga eso, sin
configurarla.

Avisa de **todos**, dure lo que dure. La duración solo se enseña si se vio
empezar: a una ventana que ya estaba trabajando cuando arrancó la isla no se le
inventa un tiempo, porque un número se lee como un dato. Lo único que lo calla es tener esa
ventana delante, porque entonces lo estás viendo. Hubo un mínimo de diez
segundos y se quitó: como el foco ya filtra lo que estás mirando, el reloj
solo servía para tragarse los avisos de lo que acaba rápido mientras estás en
otra cosa, que es justo cuando hacen falta. Si alguna CLI resulta apagar el
girador a mitad de trabajo, `TRABAJO_MINIMO` en `config.py` lo devuelve.

Lo que cuesta: un `ps` cada cinco segundos. La lista de ventanas, sus procesos
y sus títulos salen del servidor X por `ctypes`, sin lanzar `xprop` ni `xdotool`
para nada.

**Avisa de que hay un micrófono abierto.** Cualquier programa que capture
audio, no solo el dictado: el notch baja un momento con quién es y deja un
punto rojo mientras dure. Ahora que la isla sabe escuchar, lo honesto es que
sea también la que dice cuándo alguien escucha. Por eventos de PipeWire
(`pw-mon`), sin sondear, y el dictado se identifica con nombre propio para no
avisarse a sí mismo.

<p align="center">
  <img src="docs/dictado.gif" alt="Mientras hablas el notch enseña un micrófono rojo y la onda del sonido junto a la palabra Escuchando; al soltar pasa a Transcribiendo y luego a la frase transcrita con una marca verde y el logo de la IA a la que va" width="760">
</p>

**Dictado por voz.** Mantén `super + espacio`, habla y suéltalo: la isla se
despliega con la onda del micrófono, transcribe en local y escribe el texto
donde estabas. `super + shift + espacio` es el mismo dictado como interruptor, para
hablar largo sin tener la mano en la tecla.

Tres cosas que no son obvias:

**La onda es la señal real**, no una animación. Con una decorativa, un micro
silenciado se ve exactamente igual que una grabación buena, y te enteras
treinta segundos después al leer la transcripción vacía. Lo que sí es
animación es cómo llega: los niveles entran doce veces por segundo y la
pantalla va a sesenta, así que lo dibujado persigue a lo medido en vez de
copiarlo. Sin eso la onda avanza a saltos de cinco fotogramas, que es el tirón
que delata a una barra de sonido mal hecha.

**Sube rápido y baja despacio.** Grabando, la onda tiene que seguir a la voz
sin retraso o deja de ser la señal. Al soltar la tecla pasa lo contrario: lo
que quieres es *ver* cómo se cierra el micrófono, y a la velocidad de subida
eso dura 200 ms, o sea nada. Cayendo tarda 400, y se ve caer dentro de la
tarjeta que se está desvaneciendo, porque el fundido cruzado sigue dibujando
el contenido anterior mientras entra el nuevo.

Transcribiendo no hay micrófono ni onda: el micro está cerrado y ahí ya no hay
señal que enseñar. Lo único que pasa es una espera de la que nadie sabe cuánto
va a durar, y para eso basta el latido de tres puntos. Una barra de progreso
mentiría, porque whisper no informa de su avance.

**Parar no se lo puede pedir a sxhkd.** El atajo de soltado (`@super + space`)
solo casa si sueltas la `v` **antes** que super, y al levantar la mano del
teclado lo normal es lo contrario: entonces el soltado no lo ve nadie y el
dictado se queda grabando hasta el tope de dos minutos. Atar también el
soltado de super no vale, y no es teoría: `@super_l` rompe la propia
combinación, y con ella puesta dejaba de funcionar hasta el caso que antes iba
bien.

Así que mientras graba se le pregunta al servidor X si la tecla sigue pulsada,
por `ctypes` contra libX11 (`XQueryKeymap`), sin python-xlib y sin lanzar
`xinput` doce veces por segundo. Es la misma idea que leer la IP por `ioctl`
en vez de llamar a `ip`. Y como solo se vigila si la tecla estaba pulsada al
empezar, el interruptor de `super + shift + espacio` sigue funcionando: ahí está
suelta, y vigilarla pararía la grabación en el primer parpadeo.

**La ventana de destino se mira al empezar, no al terminar.** Mientras hablas
el foco puede cambiar solo —una notificación, un gesto del ratón— y el texto
acabaría escrito en cualquier parte. Al soltar, el texto va a la ventana que
tenías delante cuando empezaste.

**Sabe qué ventana tienes delante**, y se consulta cuando el foco cambia
(`bspc subscribe node_focus`), no en bucle: recorrer el árbol de procesos cada
pocos segundos para algo que casi nunca cambia sería gastar batería en nada.
Hubo un tiempo en que eso se enseñaba —el logo de la IA y la palabra
«Dictado» en reposo, al entrar el foco en una sesión de Claude Code—, y se
quitó: el dictado se lanza con su atajo, lo sepa o no el notch, y lo único que
hacía ese chip era que la fila cambiase de ancho al cambiar de ventana. El
foco se sigue mirando para otra cosa: para no avisarte de que una IA ha
terminado justo cuando la estás mirando.

**Reconoce qué IA tienes delante y enseña su logo**, no su nombre: un logo se
reconoce de un vistazo y no hay que leerlo, que es lo que se necesita de algo
que está en pantalla dos segundos. Y no lo deduce del título: una terminal con
Claude Code dentro se titula con lo que esté haciendo la conversación, así que
el título dice de qué va la ventana pero no de qué programa es. Lo que sí lo
dice es el árbol de procesos.

Reconoce `claude`, `codex` y `gemini` (`sources.IAS`). Añadir otra es una
línea ahí y un SVG en `icons/`; si falta el SVG se enseña el nombre y ya. Los
logos salen de [simple-icons](https://simpleicons.org) y se pintan como
máscara, así que el fichero no guarda el color: el blanco lo pone el tema. El
texto se escribe igual en cualquier ventana, con IA o sin ella.

**El resultado se enseña hasta en tres líneas.** Tres es el tope por una
razón de forma: a partir de ahí la tarjeta deja de ser un aviso y se convierte
en un documento, y además el texto ya está pegado donde lo vas a leer de
verdad. Lo que sobra se corta con puntos suspensivos. Es el único estado que
cambia de alto según el contenido.

**El texto se pega, no se teclea.** Medido aquí: `xdotool type` se come las
vocales acentuadas ("grabe video" por "grabé vídeo"), porque remapea un código
de tecla por cada carácter que el teclado no tiene y con el retardo por
defecto el servidor X todavía no ha procesado el mapa nuevo cuando llega la
pulsación. Con `--delay 12` sale bien, pero una frase de 300 caracteres tarda
casi cuatro segundos en aparecer. Pegar no tiene ninguno de los dos problemas:
0,1 s y el portapapeles no pasa por el mapa de teclado. El atajo depende de
dónde se pega, y esa es toda la lista que hay que mantener: Ctrl+Shift+V en
las terminales, Ctrl+V en lo demás.

A whisper se le pasa además una **pista de estilo** (`DICT_PROMPT`), que el
modelo toma como «lo que se venía diciendo» y le hace puntuar y usar
mayúsculas, que en dictado corto es donde más falla. Es deliberadamente
genérica: meter ahí jerga propia mejora esas palabras y empeora el resto,
porque el modelo intenta encajarlas donde no tocan.

Transcribe [whisper.cpp](https://github.com/ggml-org/whisper.cpp) en la
máquina, sin red. El modelo se elige midiendo, no por fama: en un portátil sin
GPU, `small-q5_1` transcribe 11 segundos de audio en 2,9 y `large-v3-turbo`
tarda 18,7, o sea más que la propia frase. Está en `config.py`.

**La ventana del codificador se ajusta a lo que has hablado**, y es la
optimización más grande que admite esto. Whisper codifica siempre 30 segundos:
hables dos o veinte, esa parte cuesta lo mismo. Recortándola (`-ac`) a los
segundos que de verdad hay, medido aquí con `small`:

| | Ventana entera | Ajustada |
|---|---|---|
| 2,5 s de audio | 2488 ms | **918 ms** |
| 11 s de audio | 4934 ms | **3075 ms** |

Con el mismo texto, coma a coma. El margen del 35% tampoco es por gusto:
quedarse corto recorta el audio y se pierden las últimas palabras, que es un
fallo mucho peor que tardar un poco más.

De punta a punta, desde que sueltas la tecla: 4 ms en cerrar el micrófono,
716 en transcribir y 133 en pegar. Con `ISLAND_DEBUG=1` esos tres números se
escriben en `$XDG_RUNTIME_DIR/island-dictado/traza.log`, que es la única forma
de saber dónde se va el tiempo: el que graba es un proceso suelto sin terminal
a la que quejarse.

Y mientras grabas, un nivel nuevo **no reconstruye el contenido del notch**:
la onda lee la lista en vivo al dibujar, así que doce veces por segundo solo
se repinta, no se vuelve a medir con Pango un texto que no ha cambiado.

**Hay un modo demo**, `dictado.py demo ["frase"]`, que recorre la tarjeta entera
sin abrir el micrófono: con él está grabado el GIF de arriba. No dibuja una onda
de adorno —eso sería enseñar algo que el programa no hace—: sintetiza audio con
la envolvente de alguien diciendo esa frase, una ráfaga por sílaba y pausas
entre palabras, y lo pasa por el **mismo `nivel()`** que procesa el micrófono. La
ventana de destino sí es la de verdad, así que lanzado desde una terminal con una
IA dentro sale su logo. El ruido lleva semilla fija: un demo que sale distinto
cada vez no sirve ni para comparar dos versiones ni para volver a grabar el
mismo GIF.

Lo que no hace, a propósito: **el micrófono no se abre solo nunca**. Se abre
cuando pulsas la tecla y se cierra cuando la sueltas. Un dictado que escucha
"por si acaso" es un micro abierto en tu escritorio todo el día.

## Cómo funciona

Una ventana `DOCK` transparente a todo el ancho, pegada arriba. No se
redimensiona nunca: lo que cambia es el dibujo. Redimensionar una ventana X11
no lo anima el compositor y se vería a saltos.

**Animación con muelles, no con curvas.** Un muelle amortiguado por cada
propiedad animada (ancho, alto, posición vertical, fundido, realce del ratón,
píldora de escritorios). La razón es que el destino puede cambiar a mitad de
animación — llega una notificación mientras se repliega otra — y un muelle
arrastra la velocidad que llevaba. Una curva de Bézier habría que reiniciarla,
y se ve el salto.

**Forma.** Canto recto arriba contra el borde de la pantalla, esquinas
redondeadas abajo, y los enlaces cóncavos donde el notch encuentra el borde.
Esos filetes son la diferencia entre parecer tallado en el panel y parecer una
pieza pegada encima.

**Eventos.** Un FIFO en `$XDG_RUNTIME_DIR`, una línea JSON por evento, y un
cliente (`island-send`) para escribir en él. Todo lo que no sea estado del
sistema entra por ahí: la regla de dunst, los scripts de volumen y brillo, y
cualquier cosa que quieras añadir tú.

```sh
island-send notify --app "CI" --body "build #284 · 2 min 14 s"
island-send panel --target launcher
island-send music --title "Midnight City" --artist "M83"
```

**120 Hz, y por qué no salían solos.** La pantalla de este portátil va a 120
y la isla pintaba a 60. No por falta de potencia: GTK3 reparte los fotogramas
con su propio reloj, y ese va fijo a 60 aunque GDK sepa perfectamente que el
monitor da 120. Medido con una ventana de prueba: GDK dice `120.00 Hz`,
`add_tick_callback` entrega **60,2 fotogramas por segundo** y un temporizador
de 8 ms entrega **119,3**.

Así que el ritmo lo lleva un temporizador y el periodo sale del monitor
(`theme.FPS = 0` para seguirlo, un número para fijarlo). Los muelles integran
con el tiempo transcurrido, no con el número de fotogramas, así que la
animación dura exactamente lo mismo a 60 que a 120: lo único que cambia es
cuántas veces se mira por el camino.

Pero con eso solo no bastaba. El bucle pasó a dar 117 vueltas por segundo y el
dibujado seguía saliendo a 58: `queue_draw_area` encola, y GTK sirve lo
pendiente a su reloj. O sea, se movían los muelles el doble de veces para
enseñar la mitad. Ahora el fotograma se pinta en el acto con
`begin_draw_frame`, que de paso se salta el doble búfer de GTK.

Comparado con el código anterior, **bajo la misma carga** y midiendo CPU por
fotograma, que es lo único que no depende de lo ocupada que esté la máquina:

| | Fotogramas | CPU por fotograma |
|---|---|---|
| Antes (60 Hz, encolado) | 227 y 233 | 2,82 y 2,79 ms |
| Ahora (120 Hz, directo) | 545 y 480 | 2,26 y 2,35 ms |

Es decir: **2,2 veces más fotogramas y cada uno un 18% más barato**. En total,
una animación cuesta ~1,9 veces más CPU que antes; eso es lo que vale el doble
de fluidez, y `FPS = 60` lo devuelve si alguna vez molesta. Lo que no cambia es
el reposo: el bucle sigue parándose en seco cuando los muelles se asientan.

Con `ISLAND_DEBUG=1` la isla escribe cada segundo cuántas vueltas da, cuántas
dibuja, lo que cuesta el fotograma medio y el peor, y cuántas veces reconstruye
el contenido. Sin eso, «optimizar» es mover cosas de sitio: las tres primeras
cosas que di por lentas --la onda del dictáfono, el margen de repintado, el
tamaño del lienzo- no aparecían en la medida.

**Coste en reposo.** El contenido se reconstruye 12 veces por minuto, no 72:
el reloj muestra `HH:MM`, así que 59 de cada 60 refrescos no cambiaban un
píxel. El bucle de animación se detiene del todo cuando los muelles se
asientan, los layouts de Pango se cachean, y la IP se lee por `ioctl` en vez
de lanzar `ip` como subproceso.

## Instalación

Hacen falta Python 3.9+, GTK 3 y PyGObject, que en Debian y derivadas son:

```sh
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-rsvg-2.0
```

Opcionales, según lo que quieras que funcione: `playerctl` (reproducción),
`nmcli` (wifi), `wpctl` de PipeWire (volumen), `dunst` (notificaciones),
`xclip` (copiar desde la calculadora), `unicode-data` más
`fonts-noto-color-emoji` para el selector de emoji, que sin la lista del
sistema te dice que falta en vez de abrirse vacío, y `scrot` para las capturas
de pantalla y de ventana. La selección de región no necesita nada: la dibuja la
propia isla.

Para el dictado hacen falta además `pw-record` (PipeWire), `xclip`, `xdotool`
(sin él el texto se queda en el portapapeles en vez de escribirse solo) y
whisper.cpp compilado:

```sh
git clone https://github.com/ggml-org/whisper.cpp ~/.local/share/whisper.cpp
cd ~/.local/share/whisper.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
./models/download-ggml-model.sh small-q5_1
```

Y `./fetch-icons.sh`, que además de los iconos de Solar baja los logos de las
IA a `icons/`. No se versionan, como el resto del arte ajeno, y aquí pesa más
el motivo: son marcas registradas. Sin ellos no se rompe nada, el notch enseña
el nombre en texto. Baja también los nombres de emoji en castellano a
`emoji-es.json`, que tampoco se versiona: es un dato derivado de algo que se
actualiza solo, y tenerlo dentro del repo significa tenerlo desactualizado.

Y el atajo, en tu `sxhkdrc`. El soltado es un atajo distinto (`@`), que es lo
que lo convierte en push-to-talk de verdad:

```
super + space
	~/.config/island/dictado.py start

@super + space
	~/.config/island/dictado.py stop
```

**Si no pasa nada al pulsarlo, mira quién más quiere esa tecla.** `ibus` se
queda `super + space` para cambiar de método de entrada y la agarra **antes**
que sxhkd, así que el atajo no llega a dispararse: no falla, es que no se
ejecuta. Se libera con

```sh
gsettings set org.freedesktop.ibus.general.hotkey triggers "@as []"
```

y el cambio de método de entrada te sigue quedando en `Ctrl+space`. Me costó
encontrarlo porque el síntoma es que no ocurre *nada*: el ayudante lanzado a
mano funcionaba, las dependencias estaban, y `super + shift + space` --que ibus
no toca- sí arrancaba.

Si cambias de tecla, cámbiala también en `DICT_TECLA` (`config.py`): es la que
el ayudante le pregunta a X para parar al soltarla. Va con el nombre que le da
X y en minúsculas --`space`, no `Space`-, porque con la mayúscula
`XStringToKeysym` devuelve 0, no se vigila nada y la grabación se queda hasta
el tope.

Y los que van a un panel de la isla, que no necesitan nada más:

```
super + period
	~/.config/island/island-send panel --target emoji

super + v
	~/.config/island/island-send panel --target portapapeles
```

Y los de las capturas. El modificador va **delante**: escrito al revés
(`@Print + ctrl`) sxhkd no casa el acorde, se queda con el `Print` pelado y
`ctrl` y `alt` acaban haciendo los tres lo mismo.

```
@Print
	~/.config/island/captura.py select

ctrl + @Print
	~/.config/island/captura.py screen

alt + @Print
	~/.config/island/captura.py window

super + shift + s
	~/.config/island/captura.py select
```

Ojo si vienes de la configuración de ejemplo de bspwm: ahí `super + .` es uno
de los cuatro saltos de nodo (`bspc node -f @second`), así que hay que
sacárselo de esa línea.

```sh
git clone https://github.com/bolado-dev/island ~/.config/island
```

En tu `bspwmrc`:

```sh
~/.config/island/launch.sh &
```

Y para que las notificaciones lleguen, al final de tu `dunstrc`:

```ini
[isla]
    appname = "*"
    script = ~/.config/island/hooks/dunst-notify.sh
    skip_display = true
```

La regla va **la última**: en dunst gana la última que casa.

## Configuración

`config.py` tiene lo que cambia de una máquina a otra — comando de bloqueo,
terminal, mezclador, nombres de las interfaces de red, los atajos de minutos
del temporizador y las duraciones del pomodoro. `theme.py` tiene el aspecto:
colores, tamaños, tipografías y las constantes del auto-ocultado.

Los perfiles de energía esperan un script que fije el EPP de `intel_pstate` y
una regla en `/etc/sudoers.d` que lo permita sin contraseña. Si no existe, el
panel enseña solo el estado de la batería en vez de botones que no harían
nada.

El juego de iconos se cambia con `USAR_SOLAR` en `theme.py`. Por defecto usa
glifos de Nerd Fonts; a `True` usa SVG de [Solar](https://www.figma.com/community/file/1166831539721848736),
que se bajan con `./fetch-icons.sh`.

## Limitaciones

- **Un solo monitor.** Se dibuja en el primero que devuelve GTK. No he
  probado nada con varios.
- **X11 y bspwm.** El indicador de escritorios habla `bspc`; el auto-ocultado
  usa `top_padding`. Portarlo a otro gestor es cambiar `sources.Bspwm`, pero
  no está hecho.
- **Las notificaciones de Chrome desde una pestaña normal no se pueden
  identificar.** Chrome no publica el origen: llegan con nombre «Google
  Chrome» y sin icono. Instalar el sitio como aplicación de Chrome sí hace que
  mande el nombre y el favicon correctos.
- **Los emoji se insertan sin tono de piel.** En la rejilla está el neutro
  y nada más: las cinco variantes multiplican por seis cada emoji de
  persona, y un selector de tono es otra interfaz encima de esta.
- **La interfaz está en español.** Las cadenas están sueltas en el código, sin
  gettext.

## Licencia

MIT.
