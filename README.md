# TALLER-2
## ANALISIS DE DATOS 
### UNIVERSIDAD YACHAY TECH 
### _AUTOR: MARIA BRIGITH SUAREZ RODRIGUEZ_

<P>
  Para este taller se pretende utilizar métodos y técnicas para el análisis de una base de datos, la misma que es de elección libre, sin embargo, su procesamiento desde la extracción de datos hasta la presentación de los mismos es entera responsabilidad de la autora.
</P>

## Objetivos 
- Extraer una base de datos del interés personal del invertigador
- Revisar y Limpiar los datos para que puedan ser procesados
- Revisar y Exponer los análisis preliminares de los datos y su comportamiento.

## Desarrollo

## PARTE 1
### 1. SELECCION BASE DE DATOS 
<p>
  En este caso en particular se escoge la base de datos publicada por el ministerio del interior, la misma que contiene todos los datos mensuales de las personas desaparecidas, por consiguiente, se utilizaron dos archivos uno que contenía los datos históricos desde el año 2017 hasta el 2025 y el archivo que contenía información desde enero a agosto del 2026.
  
  Con el fin de procesar los datos de manera uniforme una vez instaladas las librerías procedí a leer y unificar las bases de datos, sin que esto signifique borrar registros o datos, dado que la metodología y variables eran las mismas, mediante el siguiente código:
</p>

<img width="788" height="210" alt="image" src="https://github.com/user-attachments/assets/8921f8c8-3f86-4e05-af0c-7e29f98717d3" />

### 2. LIMPIEZA DE DATOS
<p>
  La limpieza de los datos es necesario para que los datos tengan un formato que permita generara procesamiento de los datos posteriormente. Para realizar este numeral se desarrollaron varios pasos: 
</p>

#### 2.1. Análisis por variable
<p>
  Implemente un código que me permitiera revisar si la variable tenia faltantes, si contenía errores y sobre todo que tipo de variable eran, obteniendo lo siguiente:
</p>
<img width="853" height="622" alt="image" src="https://github.com/user-attachments/assets/8b4a34a7-2498-4754-a495-692d38161549" />

#### 2.2. Dar formato a cada variable 

<p>
  Una vez que revise las variables procedí a darles el formato que correspondía, por ejemplo para las variables que fueran fecha como son fecha_desaparicion, fecha_denuncia, fecha_conocimiento, fecha_localizacion, se les asigno un formato de (DD/MM/AA), y para las variables que son coordenadas como latitud_desaparicion, longitud_desaparicion, latitud_localizacion, longitud_localizacion se les adecuo a que sean variables georreferenciales.
</p>
<img width="823" height="627" alt="image" src="https://github.com/user-attachments/assets/47ea21bf-7669-4214-8e27-343da575a7f9" />


<img width="848" height="320" alt="image" src="https://github.com/user-attachments/assets/63ec1314-2641-42ff-a1aa-086f55c91adb" />

#### 2.3. Rellenar los espacios en blanco 
<p>
  Al ser una base histórica que contiene varios años existe información en blanco, sin embargo, al analizar cada una de las variables notamos que:

</p>
- Los faltantes de fecha_conocimiento, latitud_localizacion, longitud_localizacion y provincia_localizacion se conservan como datos ausentes reales. El perfil los identifica como NA
- Los faltantes de motivo_desaparicion y motivacion_desaparicion_observada se reemplazan por NO ENCONTRADO
- Fecha_localizacion se mantiene como fecha real para preservar su tipo; cuando falta, una columna auxiliar, estado_fecha_localizacion, indica NO ENCONTRADO.
<img width="735" height="272" alt="image" src="https://github.com/user-attachments/assets/b2d08295-32a0-449b-8500-8039fb74f573" />
<img width="842" height="606" alt="image" src="https://github.com/user-attachments/assets/a804bbd3-5ca7-40d1-a06c-986cacd810e3" />


<p>
  Una vez que ya se ha dado formato a cada una de las variables y rellenado cada uno de los espacios en blanco, dado que al ser datos que aun no han sido cargados, no debían ser borrados.
</p>

### Subir los datos a un SQLite 

<p>
  Una vez ya realizada la limpieza de los datos se procede a guardarlos en SQLite. 
</p>
<img width="815" height="600" alt="image" src="https://github.com/user-attachments/assets/8fe19605-7c95-4bac-a753-ad0f8c44e2ba" />

## PARTE 2 EDA 

### 1. Realizar un análisis y una descripción (incluir como archivo de texto) de que información contiene el set de datos. ¿Qué puede decir o cómo puedes describir este set de datos? 

#### 1.2. Análisis descriptivo 

- Se realizo un análisis descriptivo de cada una de las variables.
- Se realizaron preguntas claves para conocer el comportamiento de los datos, siendo las siguiente:


##### P1. ¿Cuántas personas desaparecidas son menores a 17 años y están como no encontradas?
<p>
  Desde el año 2017 hasta agosto de 2026 son 792 personas menores de 17 años que hasta la fecha no han sido localizadas 
</p>

##### P2. ¿Cuáles son los principales cantones donde existen personas menores de 17 años desaparecidas y cuál es su estado de la desaparición?
<p>
  Se toma los 10 principales Cantones con las mayores desapariciones de menores de edad teniendo un total de 370 casos en investigación de los 792 casos de menores desaparecidos 
</p>
<img width="886" height="311" alt="image" src="https://github.com/user-attachments/assets/ac5356bb-8ce9-4819-b537-c543dd83d74a" />

##### P3. ¿Cuáles son los principales motivos_desaparicion de personas menores de 17 años?

<p>
  En la base base_datos_unificada.db hay 39.052 registros de personas menores de 17 años. Los principales motivos registrados son:

  <img width="886" height="349" alt="image" src="https://github.com/user-attachments/assets/61e0b84e-bed2-4839-926e-df3b91e3326b" />

</p>

<p>
  Estos datos incluyen menores con distintas situaciones actuales, no solo quienes siguen desaparecidos. Además, hay 792 registros (2,03 %) con el valor NO ENCONTRADO; es un marcador y no un motivo específico.
</p>

##### P4. ¿Cuánto tiempo pasa en promedio entre la fecha_desaparicion y la fecha_localizacion para las personas encontradas?
<p>
  El promedio es 37,34 días y la mediana es 6 días, calculados sobre 74.770 casos. 
</p>

### 2. Realizar la lectura de los datos de la base de datos utilizando Python y transformando la tabla a un dataframe de pandas. 

<img width="855" height="672" alt="image" src="https://github.com/user-attachments/assets/4c775830-0a30-4eae-a052-4ef5edb85a2f" />

### 3. Describir lo encontrado para cada uno de los campos 

<img width="528" height="662" alt="image" src="https://github.com/user-attachments/assets/0daab07b-37db-4e3b-855a-7f3315372605" />

### 4. ¿Qué meta-data se puede generar? 

<img width="843" height="607" alt="image" src="https://github.com/user-attachments/assets/96de977e-e959-4bbd-8dc4-0376fdb97286" />

# PARTE 2

<img width="1357" height="757" alt="image" src="https://github.com/user-attachments/assets/ef5701b9-db48-47e2-b0ec-604557295f76" />


La investigación debe diseñarse como un estudio longitudinal, observacional, retrospectivo y predictivo, con dos dimensiones complementarias:
1. Dimensión A. Patrones de las desapariciones: identificar tendencias temporales, perfiles registrados, concentración territorial y factores asociados con los casos reportados.
2. Dimensión B. Localización y respuesta institucional: analizar el tiempo transcurrido hasta la localización, las diferencias entre grupos y territorios, y los factores que se asocian con una localización más rápida o más lenta.

<img width="1360" height="646" alt="image" src="https://github.com/user-attachments/assets/bde21b8d-93c2-4ce1-8464-e9f0f766ffd1" />


<img width="1341" height="728" alt="image" src="https://github.com/user-attachments/assets/e31abbfb-2c65-4884-8c3f-7cb157904561" />


<img width="2671" height="1467" alt="01_situacion_actual" src="https://github.com/user-attachments/assets/4b73e155-c17a-457a-9406-6f04be0e33e5" />


<img width="2953" height="1467" alt="top_motivo_desaparicion" src="https://github.com/user-attachments/assets/ec13b903-72bb-41dd-bb04-4418b45c5faf" />
<img width="2970" height="1467" alt="top_canton" src="https://github.com/user-attachments/assets/d9f79096-daaf-4b9b-b34b-2aa98b351509" />
<img width="2967" height="1467" alt="top_sexo" src="https://github.com/user-attachments/assets/09c42927-730b-4c72-aac6-3e157de43c0b" />
<img width="2966" height="1467" alt="top_rango_edad" src="https://github.com/user-attachments/assets/9043d178-d8e8-4c05-b6e2-c8654a25c764" />
<img width="2964" height="1467" alt="top_provincia" src="https://github.com/user-attachments/assets/12f0fed6-6274-43bd-8121-522e0dd03c0b" />

<img width="1337" height="672" alt="image" src="https://github.com/user-attachments/assets/7ffc93e4-8676-4db3-8060-daf57d9f2ebe" />
<img width="4770" height="3560" alt="08_mapa_personas_encontradas_por_provincia" src="https://github.com/user-attachments/assets/cb385a85-8489-4fbc-b30c-986d216bb633" />

<img width="1346" height="727" alt="image" src="https://github.com/user-attachments/assets/2c5a5ce0-a8cd-408e-b105-fb7bcda830fb" />

<img width="1350" height="733" alt="image" src="https://github.com/user-attachments/assets/60ca58a6-28aa-4bcf-ab62-f3fccad91ffa" />

<img width="1335" height="682" alt="image" src="https://github.com/user-attachments/assets/3d863cc0-a5e9-47d6-a45f-ee5db80e3bda" />

<img width="2669" height="1469" alt="03_intervalo_denuncia" src="https://github.com/user-attachments/assets/1816263b-5ba4-4b4c-82ae-9f0497d86847" />







