(function(){
"use strict";
const $=id=>document.getElementById(id);
const GPIR_BASE_URL="https://anggaconni.github.io/GPIR/";
const CATALOG_URL=GPIR_BASE_URL+"data/opportunity_catalog.json";
const TRADE_URL=GPIR_BASE_URL+"data/data.json";
const DESIGNATED_SITES_URL=GPIR_BASE_URL+"data/designated_sites.json";
const TOURISM_PLACES_URL=GPIR_BASE_URL+"data/tourism_places.json";
const TOURISM_AREAS_URL=GPIR_BASE_URL+"config/tourism_areas.json";
const DESIGNATED_CACHE_TTL=12*60*60*1000;
const DESIGNATED_DATASETS=[
 {id:"whc001",category:"world_heritage",designation:"UNESCO World Heritage Site",url:"https://data.unesco.org/explore/dataset/whc001/api/"},
 {id:"eg0001",category:"geopark",designation:"UNESCO Global Geopark",url:"https://data.unesco.org/explore/dataset/eg0001/api/"},
 {id:"mab001",category:"biosphere_reserve",designation:"UNESCO Biosphere Reserve",url:"https://data.unesco.org/explore/dataset/mab001/api/"}
];
const POI_CACHE_TTL=3*60*60*1000;
const MARKET_FALLBACKS={
 NLD:{name:"Netherlands",lat:52.1326,lon:5.2913},DEU:{name:"Germany",lat:51.1657,lon:10.4515},
 USA:{name:"United States",lat:39.8283,lon:-98.5795},GBR:{name:"United Kingdom",lat:55.3781,lon:-3.436},
 JPN:{name:"Japan",lat:36.2048,lon:138.2529},ARE:{name:"United Arab Emirates",lat:23.4241,lon:53.8478},
 CHN:{name:"China",lat:35.8617,lon:104.1954},IND:{name:"India",lat:20.5937,lon:78.9629},
 KOR:{name:"South Korea",lat:35.9078,lon:127.7669},BRA:{name:"Brazil",lat:-14.235,lon:-51.9253},
 IDN:{name:"Indonesia",lat:-0.7893,lon:113.9213},FRA:{name:"France",lat:46.2276,lon:2.2137},
 MYS:{name:"Malaysia",lat:4.2105,lon:101.9758},SGP:{name:"Singapore",lat:1.3521,lon:103.8198}
};
const SYNONYMS={
 "singkong":["cassava","manioc","tapioca","cassava starch","cassava chips","starch"],
 "ubi kayu":["cassava","manioc","tapioca","starch"],"tapioka":["tapioca","cassava starch","starch"],
 "cassava":["cassava","manioc","tapioca","starch"],"kopi":["coffee","roasted coffee","coffee beans"],
 "kakao":["cocoa","cacao","cocoa powder"],"kelapa":["coconut","copra","coconut oil","desiccated coconut"],
 "bambu":["bamboo","bamboo products"],"rotan":["rattan","handicrafts"],"kerajinan":["handicrafts","crafts","souvenir","woven goods"],
 "suvenir":["souvenir","handicrafts","giftware"],"batik":["batik","textile","garments"],"ikan":["fish","seafood","dried fish"],
 "rempah":["spices","pepper","ginger","turmeric"],"sayur":["vegetables","fresh vegetables"],"beras":["rice"],
 "sagu":["sago","starch"],"pisang":["banana","dried fruit","banana chips"],"cokelat":["chocolate","cocoa","cacao"]
};
const COLORS={tourism:"#db2777",market:"#d97706",food_buyer:"#b45309",retail:"#2563eb",supplier:"#7c3aed",maker:"#8b5cf6",service:"#0891b2",institution:"#0f766e",other:"#64748b"};
const state={
 map:null,origin:null,originMarker:null,poiLayer:null,linkLayer:null,marketLayer:null,
 catalog:[],tradeRows:[],tradeFeed:null,tradePromise:null,countryContext:null,contextPromise:null,
 designatedSites:[],designatedPromise:null,tourismPlaces:[],tourismPromise:null,
 unTourismManifest:null,unTourismDatasets:[],unTourismDataset:null,unTourismRaw:null,unTourismHeaders:[],unTourismRecords:[],unTourismLayer:null,
 pois:[],marketSignals:[],opportunities:[],active:false,analyzeSequence:0,lastOverpassAt:0,
 localBounds:null,globalBounds:null,marketBounds:{},lastTerms:[],dataStatus:"pending",siteContext:null,poiFallbackUsed:false,poiSearchStrategy:"full query"
};
const esc=v=>String(v==null?"":v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const num=v=>v==null||v===""||!Number.isFinite(Number(v))?null:Number(v);
const clean=v=>String(v==null?"":v).normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().trim();
function km(aLat,aLon,bLat,bLon){const rad=x=>x*Math.PI/180,dLat=rad(bLat-aLat),dLon=rad(bLon-aLon),h=Math.sin(dLat/2)**2+Math.cos(rad(aLat))*Math.cos(rad(bLat))*Math.sin(dLon/2)**2;return 6371*2*Math.asin(Math.sqrt(h));}
function distanceLabel(d){return d==null?"—":d<1?Math.round(d*1000)+" m":d.toFixed(1)+" km";}
function compactUSD(v){return v==null?"Tidak tersedia":new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",notation:"compact",maximumFractionDigits:1}).format(v);}
function setStatus(message,tone="neutral"){
 const el=$("statusLine");el.textContent=message;el.className="status-line"+(tone==="error"?" error":tone==="success"?" success":"");
}
function setOverall(message,tone="gray"){
 const el=$("overallStatus");el.textContent=message;el.className="pill "+(tone==="green"?"green":tone==="gold"?"gold":"gray");
}
function poiCategory(tags){
 const t=tags||{},tour=clean(t.tourism),historic=clean(t.historic),natural=clean(t.natural),leisure=clean(t.leisure),amenity=clean(t.amenity),shop=clean(t.shop),craft=clean(t.craft),office=clean(t.office),land=clean(t.landuse);
 if(["attraction","museum","gallery","viewpoint","theme_park","zoo","aquarium","artwork","picnic_site","hotel","guest_house","hostel","camp_site"].includes(tour)||["monument","memorial","ruins","castle","archaeological_site","wayside_shrine"].includes(historic)||["beach","waterfall","hot_spring","cave_entrance"].includes(natural)||["park","garden"].includes(leisure))return "tourism";
 if(amenity==="marketplace")return "market";
 if(["restaurant","cafe","fast_food","food_court","bakery","ice_cream","bar","pub"].includes(amenity))return "food_buyer";
 if(["farmland","orchard","plant_nursery","vineyard"].includes(land)||["farm","agrarian","wholesale"].includes(shop)||office==="wholesale")return "supplier";
 if(craft||["craft","artisan"].includes(shop))return "maker";
 if(["car_repair","bicycle_repair","motorcycle_repair","tailor","electronics_repair","shoemaker"].includes(craft)||["car_repair","bicycle","motorcycle"].includes(shop)||["repair","car_repair"].includes(amenity))return "service";
 if(shop)return "retail";
 if(["hotel","guest_house","hostel","community_centre","school","university","hospital","clinic"].includes(amenity))return "institution";
 if(tour)return "tourism";
 if(office==="company"||office==="commercial")return "maker";
 return "other";
}
function poiLabel(cat){return ({tourism:"Atraksi wisata / budaya",market:"Pasar / marketplace",food_buyer:"Usaha kuliner",retail:"Toko / retail",supplier:"Pemasok / pertanian",maker:"Perajin / produsen",service:"Jasa",institution:"Fasilitas",other:"Titik peta"})[cat]||cat;}
function iconFor(cat){const color=COLORS[cat]||COLORS.other;return L.divIcon({className:"",html:'<div style="width:15px;height:15px;border:2px solid white;border-radius:50%;background:'+color+';box-shadow:0 0 0 3px '+color+'33,0 0 9px '+color+'77"></div>',iconSize:[15,15],iconAnchor:[7,7]});}
function originIcon(){return L.divIcon({className:"",html:'<div class="origin-marker">+</div>',iconSize:[28,38],iconAnchor:[14,19],popupAnchor:[0,-18]});}
function designatedText(value){
 if(value==null)return "";
 if(typeof value==="string"||typeof value==="number")return String(value).trim();
 if(Array.isArray(value))return value.map(designatedText).filter(Boolean).join("; ");
 if(typeof value==="object")return designatedText(value.name_en||value.name||value.title_en||value.label||value.country_title_en||value.country||"");
 return "";
}
function normalizeDesignatedSite(raw,definition={}){
 const row=raw&&raw.fields&&typeof raw.fields==="object"?raw.fields:(raw&&raw.record&&raw.record.fields&&typeof raw.record.fields==="object"?raw.record.fields:raw||{});
 const value=(keys)=>{for(const key of keys){const v=row[key];if(v!==undefined&&v!==null&&v!==""&&!(Array.isArray(v)&&!v.length))return v;}return "";};
 const name=designatedText(value(["name","name_en","title_en","site_name_en","site_name","name_of_site","property_name","title"]));
 if(!name)return null;
 let coordinates=value(["coordinates","geo_point_2d","geo_point","location"]),lat=null,lon=null;
 const coordinateNumber=v=>v==null||v===""?null:Number(v);
 if(Array.isArray(coordinates)&&coordinates.length>=2){lat=coordinateNumber(coordinates[0]);lon=coordinateNumber(coordinates[1]);}
 else if(coordinates&&typeof coordinates==="object"){lat=coordinateNumber(coordinates.lat??coordinates.latitude);lon=coordinateNumber(coordinates.lon??coordinates.lng??coordinates.longitude);}
 else if(typeof coordinates==="string"){
  try{const decoded=JSON.parse(coordinates);if(Array.isArray(decoded)&&decoded.length>=2){lat=coordinateNumber(decoded[0]);lon=coordinateNumber(decoded[1]);}}catch(_){}
  if(!Number.isFinite(lat)||!Number.isFinite(lon)){const found=coordinates.match(/-?\d+(?:\.\d+)?/g)||[];if(found.length>=2){lat=coordinateNumber(found[0]);lon=coordinateNumber(found[1]);}}
 }
 if(!Number.isFinite(lat)||!Number.isFinite(lon)){
  lat=coordinateNumber(value(["latitude","lat"]));lon=coordinateNumber(value(["longitude","lon","lng"]));
 }
 if(!Number.isFinite(lat)||!Number.isFinite(lon)||lat<-90||lat>90||lon<-180||lon>180)return null;
 const country=designatedText(value(["country","country_title_en","country_name_en","country_name","countries_en","countries","states_names_en","states_name_en","states_names","state_party","states_parties","country_en","iso2"]))||"Country not specified";
 const category=String(value(["category"])||definition.category||"").trim()||"other";
 const designation=designatedText(value(["designation"]))||definition.designation||"UNESCO-designated site";
 const dataset=String(value(["source_dataset"])||definition.id||"unesco");
 const external=designatedText(value(["external_id","id_no","mab_id","uuid","id","code"]))||name.toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"");
 let url=designatedText(value(["url","website","site_url"]));
 if(!url&&dataset==="whc001")url="https://whc.unesco.org/en/list/"+external+"/";
 const sourceUrl=designatedText(value(["source_url"]))||definition.url||"https://data.unesco.org/";
 return {
  id:String(value(["id"])||dataset+":"+external),external_id:external,name,country,
  country_code:designatedText(value(["country_code","iso2","iso3","country_iso2","country_iso3"])),
  category,designation,lat,lon,url,source_dataset:dataset,source:"UNESCO DataHub",source_url:sourceUrl,
  inscription_year:designatedText(value(["inscription_year","date_inscribed","year_inscribed","date"])),
  license:designatedText(value(["license"]))||"CC BY-SA 4.0"
 };
}
async function fetchLiveDesignatedDataset(definition){
 const items=[];let offset=0,pages=0,total=null;
 while(pages<30){
  const url="https://data.unesco.org/api/explore/v2.1/catalog/datasets/"+encodeURIComponent(definition.id)+"/records?limit=100&offset="+offset;
  const response=await fetch(url,{headers:{Accept:"application/json"}});
  if(!response.ok)throw new Error(definition.id+" HTTP "+response.status);
  const payload=await response.json(),rows=Array.isArray(payload.results)?payload.results:[];
  rows.forEach(row=>{const site=normalizeDesignatedSite(row,definition);if(site)items.push(site);});
  pages++;offset+=rows.length;total=Number(payload.total_count);
  if(!rows.length||rows.length<100||(Number.isFinite(total)&&offset>=total))break;
 }
 return {items,pages};
}
function siteCountryList(site){
 return String(site.country||"Country not specified").split(/[;,]/).map(v=>v.trim()).filter(Boolean);
}
function siteLabel(site){return site.name+" — "+site.country+" · "+(site.designation||site.source||"");}
function destinationSource(){return $("destinationSourceFilter").value||"tourism";}
function currentDestinationItems(){return destinationSource()==="unesco"?state.designatedSites:state.tourismPlaces;}
function destinationCategoryLabels(){
 return {
  travel_guide:"Travel guide / destination",
  tourist_attraction:"Tourist attraction",
  cultural_attraction:"Cultural attraction",
  nature_attraction:"Nature attraction",
  visitor_attraction:"Visitor attraction",
  arts_and_crafts:"Arts & crafts",
  point_of_interest:"Point of interest",
  world_heritage:"World Heritage Site",
  geopark:"UNESCO Global Geopark",
  biosphere_reserve:"UNESCO Biosphere Reserve"
 };
}
function populateDestinationFilters(){
 const source=destinationSource(),categorySelect=$("designationFilter"),countrySelect=$("designationCountryFilter");
 const oldCategory=categorySelect.value,oldCountry=countrySelect.value;
 if(source==="unesco"){
  categorySelect.innerHTML='<option value="all">Semua situs UNESCO</option><option value="world_heritage">World Heritage Site</option><option value="geopark">Global Geopark</option><option value="biosphere_reserve">Biosphere Reserve</option>';
 }else{
  const labels=destinationCategoryLabels(),available=[...new Set(state.tourismPlaces.map(site=>site.category).filter(Boolean))].sort((a,b)=>(labels[a]||a).localeCompare(labels[b]||b));
  const options=[["all","Semua destinasi wisata"],...available.map(value=>[value,labels[value]||value.replaceAll("_"," ")])];
  categorySelect.innerHTML=options.map(([value,label])=>'<option value="'+value+'">'+label+'</option>').join("");
 }
 if([...categorySelect.options].some(o=>o.value===oldCategory))categorySelect.value=oldCategory;
 else categorySelect.value="all";
 const items=currentDestinationItems();
 const countries=[...new Set(items.flatMap(siteCountryList).filter(name=>name&&name!=="Country not specified"))].sort((a,b)=>a.localeCompare(b));
 countrySelect.innerHTML='<option value="all">Semua negara</option>'+countries.map(name=>'<option value="'+esc(name)+'">'+esc(name)+'</option>').join("");
 if(countries.some(name=>clean(name)===clean(oldCountry)))countrySelect.value=countries.find(name=>clean(name)===clean(oldCountry));
 else countrySelect.value="all";
 const note=$("destinationSourceNote");
 if(note){
  note.innerHTML=source==="unesco"
   ? 'Situs resmi UNESCO dengan titik koordinat referensi. <a href="https://data.unesco.org/" target="_blank" rel="noopener noreferrer">UNESCO DataHub ↗</a>'
   : 'Katalog saat ini memuat '+state.tourismPlaces.length+' titik panduan wisata berkoordinat; ini bukan inventaris atraksi global lengkap. <a href="https://www.untourism.int/tourism-statistics/tourism-statistics-database" target="_blank" rel="noopener noreferrer">UN Tourism Statistics ↗</a> berisi statistik negara/region, bukan koordinat atraksi.';
 }
}
function designatedSiteMatches(query=""){
 const q=clean(query),category=$("designationFilter").value,country=$("designationCountryFilter").value;
 return currentDestinationItems().filter(site=>{
  if(category!=="all"&&site.category!==category)return false;
  if(country!=="all"&&!siteCountryList(site).some(name=>clean(name)===clean(country)))return false;
  if(!q)return true;
  return clean(site.name).includes(q)||clean(site.country).includes(q)||clean(site.designation||"").includes(q)||clean(siteLabel(site)).includes(q)||clean(site.source||"").includes(q);
 }).sort((a,b)=>a.country.localeCompare(b.country)||a.name.localeCompare(b.name));
}
function designatedSiteStatus(message,tone="neutral"){
 const el=$("designatedSiteStatus");if(!el)return;
 el.textContent=message;
 el.style.color=tone==="error"?"#9f2d2d":tone==="success"?"#17664f":"";
}
function closeDesignatedSiteOptions(){
 const list=$("designatedSiteOptions");if(!list)return;
 list.hidden=true;$("designatedSiteSearch").setAttribute("aria-expanded","false");
}
function renderDesignatedSiteOptions(open=true){
 const list=$("designatedSiteOptions"),input=$("designatedSiteSearch");
 if(!list||!input)return;
 const source=destinationSource(),items=currentDestinationItems(),matches=designatedSiteMatches(input.value),shown=matches.slice(0,80);
 list.innerHTML=shown.length?shown.map(site=>'<button type="button" class="destination-option" role="option" data-destination-id="'+esc(site.id)+'"><span class="destination-option-title">'+esc(site.name)+'</span><span class="destination-option-meta">'+esc(site.country)+' · '+esc(site.designation||site.source||"Tourism destination")+'</span></button>').join(""):'<div class="destination-option-empty">'+(items.length?"Tidak ada destinasi yang cocok. Ubah jenis/negara atau kata pencarian.":source==="unesco"?"Katalog UNESCO belum tersedia. Coba pencarian lokasi biasa.":"Katalog wisata belum tersedia. Coba pencarian lokasi biasa.")+'</div>';
 list.hidden=!open;
 input.setAttribute("aria-expanded",open?"true":"false");
 list.querySelectorAll("[data-destination-id]").forEach(button=>button.addEventListener("click",()=>goToDesignatedSite(button.dataset.destinationId)));
 if(matches.length>shown.length)designatedSiteStatus("Menampilkan "+shown.length+" dari "+matches.length+" hasil. Tambahkan kata pencarian atau pilih negara.");
 else if(items.length)designatedSiteStatus(matches.length+" destinasi cocok · pilih salah satu untuk memindahkan pin.", "success");
 else if(source==="tourism")designatedSiteStatus("Katalog wisata tidak tersedia saat ini. Kolom Cari lokasi tetap dapat digunakan.","error");
 else designatedSiteStatus("Katalog UNESCO belum tersedia. Kolom Cari lokasi tetap dapat digunakan.","error");
}
function goToDesignatedSite(id){
 const site=currentDestinationItems().find(item=>item.id===id);if(!site)return;
 $("designatedSiteSearch").value=site.name;
 $("locationSearch").value=site.name+", "+site.country;
 closeDesignatedSiteOptions();
 const source=destinationSource();
 const zoom=source==="unesco"?(site.category==="world_heritage"?11:9):(site.category==="travel_guide"?11:13);
 const label=site.name+" · "+(site.designation||site.source||"Tourism destination")+" · "+site.country;
 setOrigin({lat:site.lat,lng:site.lon},true,label);
 state.map.setView([site.lat,site.lon],zoom);
}
async function ensureTourismPlaces(){
 if(state.tourismPlaces.length)return state.tourismPlaces;
 if(state.tourismPromise)return state.tourismPromise;
 state.tourismPromise=(async()=>{
  designatedSiteStatus("Memuat katalog Tourism destinations…");
  const cached=cacheRead("gpir:tourism-places:v1",DESIGNATED_CACHE_TTL);
  if(Array.isArray(cached)&&cached.length){
   state.tourismPlaces=cached;
  }else{
   const results=await Promise.allSettled([
    fetch(TOURISM_PLACES_URL,{cache:"no-cache",headers:{Accept:"application/json"}}).then(response=>{if(!response.ok)throw new Error("Tourism catalogue HTTP "+response.status);return response.json();}),
    fetch(TOURISM_AREAS_URL,{cache:"no-cache",headers:{Accept:"application/json"}}).then(response=>{if(!response.ok)throw new Error("Tourism area index HTTP "+response.status);return response.json();})
   ]);
   const payload=results[0].status==="fulfilled"?results[0].value:null;
   const areaPayload=results[1].status==="fulfilled"?results[1].value:null;
   const areaMap=new Map(((areaPayload&&areaPayload.areas)||[]).map(area=>[String(area.id),area]));
   const rows=payload&&Array.isArray(payload.items)?payload.items:[];
   state.tourismPlaces=rows.map(row=>{
    const area=areaMap.get(String(row.seed_area_id||""))||{};
    const lat=num(row.lat),lon=num(row.lon);
    if(!row.id||!row.name||lat==null||lon==null||lat<-90||lat>90||lon<-180||lon>180)return null;
    return {
     id:String(row.id),name:String(row.name),country:String(row.country||area.country||row.seed_area_name||"Country not specified"),
     country_code:String(row.country_code||area.iso2||""),lat,lon,
     category:String(row.category||"travel_guide"),designation:row.category==="travel_guide"?"Travel guide / destination":"Tourism destination",
     source:String(row.source||"Tourism places catalogue"),url:String(row.url||""),source_url:String(row.source_url||""),
     seed_area_name:String(row.seed_area_name||area.name||""),kind:String(row.kind||"tourism_destination")
    };
   }).filter(Boolean).sort((a,b)=>a.country.localeCompare(b.country)||a.name.localeCompare(b.name));
   if(state.tourismPlaces.length)cacheWrite("gpir:tourism-places:v1",state.tourismPlaces);
   else if(results[0].status==="rejected")throw results[0].reason;
  }
  return state.tourismPlaces;
 })();
 try{return await state.tourismPromise;}finally{state.tourismPromise=null;}
}
async function ensureDesignatedSites(){
 if(state.designatedSites.length)return state.designatedSites;
 if(state.designatedPromise)return state.designatedPromise;
 state.designatedPromise=(async()=>{
  designatedSiteStatus("Memuat katalog UNESCO…");
  let items=[];
  const cached=cacheRead("gpir:designated-sites:v1",DESIGNATED_CACHE_TTL);
  if(Array.isArray(cached)&&cached.length)items=cached;
  if(!items.length){
   try{
    const response=await fetch(DESIGNATED_SITES_URL,{cache:"no-cache",headers:{Accept:"application/json"}});
    if(response.ok){
     const payload=await response.json(),rows=Array.isArray(payload.items)?payload.items:[];
     items=rows.map(row=>normalizeDesignatedSite(row,{id:row.source_dataset,category:row.category,designation:row.designation,url:row.source_url})).filter(Boolean);
    }
   }catch(_){}
  }
  if(!items.length){
   const outcomes=await Promise.allSettled(DESIGNATED_DATASETS.map(fetchLiveDesignatedDataset));
   outcomes.forEach((result,index)=>{if(result.status==="fulfilled")items.push(...result.value.items);else console.warn("UNESCO dataset unavailable",DESIGNATED_DATASETS[index].id,result.reason);});
   if(items.length)cacheWrite("gpir:designated-sites:v1",items);
  }
  const unique=new Map();
  items.forEach(site=>{if(site&&site.id&&Number.isFinite(site.lat)&&Number.isFinite(site.lon))unique.set(site.id,site);});
  state.designatedSites=[...unique.values()].sort((a,b)=>a.country.localeCompare(b.country)||a.name.localeCompare(b.name));
  if(state.designatedSites.length){
   designatedSiteStatus(state.designatedSites.length.toLocaleString()+" situs tersedia dari UNESCO DataHub. Filter menurut jenis situs dan negara, atau ketik nama.");
  }else{
   designatedSiteStatus("Katalog situs UNESCO belum dapat dimuat. Pencarian lokasi biasa tetap tersedia.", "error");
  }
  return state.designatedSites;
 })();
 try{return await state.designatedPromise;}finally{state.designatedPromise=null;}
}
async function ensureDestinationSource(){
 try{
  const source=destinationSource();
  if(source==="unesco")await ensureDesignatedSites();
  else await ensureTourismPlaces();
  populateDestinationFilters();
  return currentDestinationItems();
 }catch(error){
  console.warn("Destination catalog load failed",error);
  designatedSiteStatus("Katalog tidak dapat dimuat: "+error.message+". Gunakan Cari lokasi untuk mencari tempat.","error");
  return [];
 }
}
function initDesignatedSitePicker(){
 const input=$("designatedSiteSearch"),toggle=$("toggleDesignatedSiteOptions"),list=$("designatedSiteOptions");
 input.addEventListener("focus",()=>{ensureDestinationSource().then(()=>renderDesignatedSiteOptions(true));});
 input.addEventListener("input",()=>{renderDesignatedSiteOptions(true);});
 input.addEventListener("keydown",event=>{
  if(event.key==="ArrowDown"){event.preventDefault();renderDesignatedSiteOptions(true);const first=list.querySelector("[data-destination-id]");if(first)first.focus();return;}
  if(event.key==="Escape"){closeDesignatedSiteOptions();return;}
  if(event.key!=="Enter")return;
  event.preventDefault();
  const query=clean(input.value),matches=designatedSiteMatches(input.value);
  const exact=matches.find(site=>clean(site.name)===query||clean(siteLabel(site))===query);
  if(exact){goToDesignatedSite(exact.id);return;}
  if(matches.length===1){goToDesignatedSite(matches[0].id);return;}
  if(matches.length>1){renderDesignatedSiteOptions(true);designatedSiteStatus(matches.length+" hasil ditemukan. Pilih salah satu situs dalam daftar.");return;}
  if(query.length>=3){$("locationSearch").value=input.value;closeDesignatedSiteOptions();searchLocation();return;}
  renderDesignatedSiteOptions(true);
 });
 toggle.addEventListener("click",()=>{ensureDestinationSource().then(()=>{if(list.hidden)renderDesignatedSiteOptions(true);else closeDesignatedSiteOptions();});});
 $("destinationSourceFilter").addEventListener("change",()=>{
  $("designatedSiteSearch").value="";
  populateDestinationFilters();
  ensureDestinationSource().then(()=>renderDesignatedSiteOptions(!list.hidden));
 });
 ["designationFilter","designationCountryFilter"].forEach(id=>$(id).addEventListener("change",()=>renderDesignatedSiteOptions(!list.hidden)));
 document.addEventListener("click",event=>{if(!event.target.closest(".destination-combo"))closeDesignatedSiteOptions();});
 list.addEventListener("keydown",event=>{if(event.key==="Escape"){closeDesignatedSiteOptions();input.focus();}});
 ensureDestinationSource().then(()=>renderDesignatedSiteOptions(false)).catch(error=>{console.warn("Destination catalogue failed",error);designatedSiteStatus("Katalog tidak tersedia. Gunakan Cari lokasi untuk mencari nama tempat.","error");});
}
const UN_TOURISM_MANIFEST_URL=GPIR_BASE_URL+"data/un_tourism/manifest.json";
const UN_TOURISM_SHEETS_URL=GPIR_BASE_URL+"data/un_tourism/sheets/";
function statKey(value){return clean(value).replace(/[^a-z0-9]/g,"");}
function statKeyAt(headers,exacts,contains=[]){
 const keys=headers.map(statKey);
 for(const exact of exacts){const i=keys.indexOf(statKey(exact));if(i>=0)return i;}
 for(let i=0;i<keys.length;i++)if(contains.some(part=>keys[i].includes(statKey(part))))return i;
 return -1;
}
function statYearHeaders(headers){
 return headers.map((h,i)=>({index:i,year:Number(String(h||"").trim())}))
  .filter(x=>/^(19|20)\d{2}$/.test(String(x.year)));
}
function statDatasetTitle(item){
 const name=clean(item.workbook||"").replace(/_/g," ").replace(/\.xlsx?$/i,"");
 const rules=[
  [/inbound arrivals by region/,"International arrivals by region"],
  [/inbound arrivals by purpose/,"International arrivals by purpose"],
  [/inbound arrivals by transport/,"International arrivals by transport"],
  [/inbound arrivals/,"International tourist arrivals"],
  [/inbound expenditure/,"International visitor expenditure"],
  [/outbound departures/,"Outbound departures"],
  [/outbound expenditure/,"Outbound visitor expenditure"],
  [/domestic trips/,"Domestic tourist trips"],
  [/domestic accommodation/,"Domestic tourism accommodation"],
  [/inbound accommodation/,"Inbound tourism accommodation"],
  [/accommodation hotels/,"Hotel indicators"],
  [/accommodation other indicators/,"Other accommodation indicators"],
  [/tdgdp/,"Tourism contribution to GDP (SDG 8.9.1)"],
  [/employed persons/,"Tourism employment (SDG 8.9.2)"],
  [/tsa seea/,"Tourism Satellite Account / SEEA (SDG 12.b.1)"]
 ];
 return (rules.find(([re])=>re.test(name))||[null,(item.workbook||"UN Tourism dataset")])[1];
}
function setUnTourismStatus(message,tone="neutral"){
 const el=$("unTourismStatus");if(!el)return;
 el.textContent=message;
 el.className="status-line"+(tone==="error"?" error":tone==="success"?" success":"");
}
async function loadUnTourismManifest(){
 const select=$("unTourismDatasetSelect");
 try{
  const response=await fetch(UN_TOURISM_MANIFEST_URL,{cache:"no-cache",headers:{Accept:"application/json"}});
  if(!response.ok)throw new Error("Manifest HTTP "+response.status);
  const manifest=await response.json();
  const dataSheets=(manifest.worksheets||[]).filter(item=>item.worksheet==="Data"&&item.file);
  if(!dataSheets.length)throw new Error("Manifest tidak berisi data sheet yang dapat dipilih");
  state.unTourismManifest=manifest;
  state.unTourismDatasets=dataSheets;
  select.innerHTML=dataSheets.map(item=>'<option value="'+esc(item.file)+'">'+esc(statDatasetTitle(item))+' · '+Number(item.rows||0).toLocaleString("id-ID")+' baris</option>').join("");
  select.disabled=false;
  const preferred=dataSheets.find(item=>/inbound_arrivals_12_2025__02_Data/i.test(item.file))||
   dataSheets.find(item=>/inbound_arrivals.*02_Data/i.test(item.file))||
   dataSheets[0];
  if(preferred)select.value=preferred.file;
  setUnTourismStatus("Manifest tersedia · "+dataSheets.length+" dataset resmi. Pilih satu dataset lalu klik Muat statistik.");
 }catch(error){
  select.innerHTML='<option value="">Dataset tidak tersedia</option>';select.disabled=true;
  setUnTourismStatus("Gagal memuat manifest UN Tourism: "+error.message,"error");
 }
}
function normalizeUnTourismWorksheet(raw,item){
 const grid=Array.isArray(raw.data)?raw.data:[];
 if(!grid.length)return {headers:[],records:[]};
 const headers=grid[0].map((h,i)=>String(h==null||h===""?"Column "+(i+1):h).trim());
 const countryIdx=statKeyAt(headers,["reporter_area_label","country_name","country","area_label","area_name","geo_area_name","geoareaname","reference_area","ref_area_label","geography"],["countryname"]);
 const countryCodeIdx=statKeyAt(headers,["country_iso3","country_iso3_code","iso3","iso3_code","reporter_iso3","reporter_area_code","reporterareacode"],["countryiso3","iso3code"]);
 const yearIdx=statKeyAt(headers,["year","time_period","time","period","reference_year"]);
 const valueIdx=statKeyAt(headers,["value","obs_value","observation_value","data_value","observationvalue"]);
 const indicatorIdx=statKeyAt(headers,["indicator_label","indicator_name","indicator","series_name","measure_label","variable"]);
 const unitIdx=statKeyAt(headers,["unit","unit_of_measure","unit_measure","measurement_unit"]);
 const wideYears=statYearHeaders(headers),longForm=yearIdx>=0&&valueIdx>=0,records=[];
 const baseIndices=new Set([countryIdx,countryCodeIdx,yearIdx,valueIdx,indicatorIdx,unitIdx,...wideYears.map(x=>x.index)].filter(i=>i>=0));
 headers.forEach((h,i)=>{if(/^(indicatorcode|indicatorpreviouscode|reporterareacode|partnerareacode|flag|flaglabel|notes|note|source|sourceurl|unitcode|obsstatus|observationstatus)$/.test(statKey(h)))baseIndices.add(i);});
 for(let ri=1;ri<grid.length;ri++){
  const row=grid[ri]||[];if(!row.some(v=>v!==null&&v!==""))continue;
  let country=countryIdx>=0?row[countryIdx]:null;
  if(country==null||country===""){
   const firstString=row.find(v=>typeof v==="string"&&v.trim());country=firstString||"Area not identified";
  }
  const countryCode=countryCodeIdx>=0?String(row[countryCodeIdx]??"").trim():"";
  const indicator=indicatorIdx>=0&&row[indicatorIdx]!=null&&row[indicatorIdx]!==""?String(row[indicatorIdx]):statDatasetTitle(item);
  const unit=unitIdx>=0?row[unitIdx]:null,extras={};
  headers.forEach((h,i)=>{if(!baseIndices.has(i)&&row[i]!=null&&row[i]!=="")extras[h]=row[i];});
  const classification=Object.entries(extras).filter(([k])=>!/^(flag|flag label|notes?|indicator code|indicator previous code)$/i.test(k)).map(([k,v])=>k+": "+v).join(" · ");
  const add=(year,value)=>records.push({country:String(country),countryCode,year,value:num(value),indicator:String(indicator),unit:unit==null?"":String(unit),classification,extras});
  if(longForm)add(row[yearIdx]==null?null:num(row[yearIdx]),row[valueIdx]);
  else if(wideYears.length)wideYears.forEach(y=>{const v=num(row[y.index]);if(v!=null)add(y.year,v);});
  else{
   const numericIdx=row.findIndex((v,i)=>i!==countryIdx&&num(v)!=null);
   add(null,numericIdx>=0?row[numericIdx]:null);
  }
 }
 return {headers,records};
}
function preferredUnTourismIndicator(records,dataset){
 const names=[...new Set(records.map(row=>row.indicator).filter(Boolean))];
 const title=clean(statDatasetTitle(dataset));
 const regex=title.includes("expenditure")?/expenditure|spending/i:
  title.includes("trip")?/trip|travel/i:
  title.includes("accommodation")||title.includes("hotel")?/accommodation|hotel|bed|room/i:
  title.includes("employment")?/employ|persons/i:
  title.includes("gdp")?/gdp|tourism direct/i:
  /arrival|arriv/i;
 return names.find(name=>regex.test(name))||names[0]||"";
}
function populateUnTourismFilters(){
 const records=state.unTourismRecords;
 const indicators=[...new Set(records.map(row=>row.indicator).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
 const indicatorSelect=$("unTourismIndicatorSelect");
 indicatorSelect.innerHTML=indicators.map(name=>'<option value="'+esc(name)+'">'+esc(name)+'</option>').join("");
 const dataset=state.unTourismDataset;
 const preferred=preferredUnTourismIndicator(records,dataset);
 if(indicators.includes(preferred))indicatorSelect.value=preferred;
 const years=[...new Set(records.map(row=>row.year).filter(Number.isFinite))].sort((a,b)=>a-b);
 $("unTourismYearSelect").innerHTML=years.map(year=>'<option value="'+year+'">'+year+'</option>').join("");
 if(years.length)$("unTourismYearSelect").value=String(years[years.length-1]);
 const breakdown=$("unTourismBreakdownSelect");
 const skip=new Set(["indicatorcode","indicatorpreviouscode","reporterareacode","partnerareacode","flag","flaglabel","notes","note","source","sourceurl","unit","unitofmeasure","year","value","indicatorlabel","indicatorname","indicator","country","countryname","reporterarealabel","arealabel","areaname","geoareaname"]);
 const fields=state.unTourismHeaders.filter(h=>!skip.has(statKey(h))).map(key=>({
  key,values:[...new Set(records.map(row=>row.extras[key]).filter(v=>v!=null&&v!=="").map(String))]
 })).filter(field=>field.values.length>1&&field.values.length<=80).sort((a,b)=>{
  const priority=["total","purpose","transport","partner","region","sex","type","category"];
  const score=field=>{const i=priority.findIndex(value=>statKey(field.key).includes(value));return i<0?99:i;};
  return score(a)-score(b)||a.key.localeCompare(b.key);
 });
 breakdown.innerHTML='<option value="">Auto · hanya negara dengan satu nilai</option>'+fields.flatMap(field=>field.values.map(value=>'<option value="'+esc(field.key+"::"+value)+'">'+esc(field.key+" = "+value)+'</option>')).join("");
 $("unTourismFilters").hidden=records.length===0;
 $("unTourismShowBtn").disabled=!years.length||!indicators.length;
}
async function loadUnTourismDataset(){
 const file=$("unTourismDatasetSelect").value;
 const dataset=state.unTourismDatasets.find(item=>item.file===file);
 if(!dataset){setUnTourismStatus("Pilih dataset UN Tourism terlebih dahulu.","error");return;}
 const button=$("unTourismLoadBtn");button.disabled=true;button.textContent="Memuat…";
 $("unTourismFilters").hidden=true;
 setUnTourismStatus("Mengunduh dan membaca "+statDatasetTitle(dataset)+"… File besar dapat memerlukan beberapa saat.");
 try{
  const response=await fetch(UN_TOURISM_SHEETS_URL+encodeURIComponent(dataset.file),{cache:"force-cache",headers:{Accept:"application/json"}});
  if(!response.ok)throw new Error("Dataset HTTP "+response.status);
  const raw=await response.json(),parsed=normalizeUnTourismWorksheet(raw,dataset);
  if(!parsed.records.length)throw new Error("Worksheet tidak menghasilkan observasi yang dapat dibaca. Periksa header data.");
  state.unTourismDataset=dataset;state.unTourismRaw=raw;state.unTourismHeaders=parsed.headers;state.unTourismRecords=parsed.records;
  populateUnTourismFilters();
  const years=[...new Set(parsed.records.map(row=>row.year).filter(Number.isFinite))];
  setUnTourismStatus("Dataset siap · "+parsed.records.length.toLocaleString("id-ID")+" observasi · "+new Set(parsed.records.map(row=>row.country)).size+" negara/area · tahun "+(years.length?Math.min(...years)+"–"+Math.max(...years):"tidak tersedia")+". Pilih indikator/tahun, lalu tampilkan di peta.","success");
 }catch(error){
  state.unTourismDataset=null;state.unTourismRaw=null;state.unTourismHeaders=[];state.unTourismRecords=[];
  setUnTourismStatus("Gagal memuat statistik: "+error.message,"error");
 }finally{button.disabled=false;button.textContent="Muat statistik";}
}
function mapCountryCoordinate(row,countries){
 const iso=String(row.countryCode||"").toUpperCase();
 if(/^[A-Z]{3}$/.test(iso)&&countries[iso]){
  const c=countries[iso],lat=num(c.latitude),lon=num(c.longitude);
  if(lat!=null&&lon!=null)return {iso,lat,lon,name:c.name||row.country};
 }
 const target=clean(row.country).replace(/^the /,"");
 for(const [code,country] of Object.entries(countries)){
  const candidate=clean(country.name||"").replace(/^the /,"");
  if(candidate===target||candidate.replace(/[^a-z0-9]/g,"")===target.replace(/[^a-z0-9]/g,"")){
   const lat=num(country.latitude),lon=num(country.longitude);
   if(lat!=null&&lon!=null)return {iso:code,lat,lon,name:country.name||row.country};
  }
 }
 const aliases={
  "united states of america":"united states","usa":"united states","russian federation":"russia",
  "viet nam":"vietnam","iran islamic republic of":"iran","lao peoples democratic republic":"laos",
  "republic of korea":"south korea","democratic peoples republic of korea":"north korea",
  "bolivia plurinational state of":"bolivia","venezuela bolivarian republic of":"venezuela",
  "türkiye":"turkey","czechia":"czech republic","brunei darussalam":"brunei"
 };
 const alias=aliases[target];
 if(alias){
  for(const [code,country] of Object.entries(countries)){
   if(clean(country.name||"")===alias){
    const lat=num(country.latitude),lon=num(country.longitude);
    if(lat!=null&&lon!=null)return {iso:code,lat,lon,name:country.name||row.country};
   }
  }
 }
 return null;
}
function renderUnTourismLayer(){
 if(!state.unTourismRecords.length||!state.unTourismDataset){setUnTourismStatus("Muat dataset terlebih dahulu.","error");return;}
 const indicator=$("unTourismIndicatorSelect").value,year=num($("unTourismYearSelect").value),breakdown=$("unTourismBreakdownSelect").value;
 const rows=state.unTourismRecords.filter(row=>row.indicator===indicator&&row.year===year&&row.value!=null&&(
  !breakdown||String(row.extras[breakdown.slice(0,breakdown.indexOf("::"))]??"")===breakdown.slice(breakdown.indexOf("::")+2)
 ));
 if(!rows.length){setUnTourismStatus("Tidak ada nilai untuk indikator dan tahun tersebut. Pilih filter lain.","error");return;}
 const byCountry=new Map();
 rows.forEach(row=>{const key=clean(row.country);if(!byCountry.has(key))byCountry.set(key,[]);byCountry.get(key).push(row);});
 const uniqueRows=[],ambiguous=[];
 for(const group of byCountry.values()){
  if(group.length===1)uniqueRows.push(group[0]);else ambiguous.push(group[0].country);
 }
 const showBtn=$("unTourismShowBtn");showBtn.disabled=true;showBtn.textContent="Menyiapkan layer…";
 Promise.resolve(ensureCountryContext()).then(context=>{
  const countries=context&&context.countries||{},points=[];
  uniqueRows.forEach(row=>{const coordinate=mapCountryCoordinate(row,countries);if(coordinate)points.push({row,coordinate});});
  const layer=state.unTourismLayer;
  layer.clearLayers();
  if(state.map.hasLayer(layer))state.map.removeLayer(layer);
  if(!points.length){
   setUnTourismStatus("Tidak ada titik negara yang cocok dengan nama pada dataset ini. Data statistik tidak dipetakan agar lokasi tidak ditebak.","error");
   return;
  }
  const maxValue=Math.max(...points.map(point=>Math.abs(point.row.value)),1);
  const units=[...new Set(points.map(point=>point.row.unit).filter(Boolean))];
  points.forEach(({row,coordinate})=>{
   const ratio=Math.log1p(Math.abs(row.value))/Math.log1p(maxValue);
   const radius=5+Math.round(10*ratio);
   const marker=L.circleMarker([coordinate.lat,coordinate.lon],{
    radius,weight:1.5,color:"#ffffff",opacity:1,fillColor:"#2563eb",fillOpacity:.72
   });
   const valueText=new Intl.NumberFormat("id-ID",{maximumFractionDigits:2}).format(row.value);
   const unitText=row.unit?" "+esc(row.unit):"";
   const sourceUrl="https://www.untourism.int/tourism-statistics/tourism-statistics-database";
   marker.bindPopup('<div class="potential-popup"><b>'+esc(coordinate.name)+'</b><div>'+esc(row.indicator)+'</div><p><strong>'+esc(valueText)+unitText+'</strong></p><small>Tahun '+esc(row.year)+' · Statistik nasional/area, bukan hitungan pengunjung atraksi.</small><br><a href="'+sourceUrl+'" target="_blank" rel="noopener noreferrer">Sumber: UN Tourism ↗</a></div>');
   marker.bindTooltip(coordinate.name+": "+valueText,{direction:"top",sticky:true});
   marker.addTo(layer);
  });
  layer.addTo(state.map);
  state.map.setView([18,10],2);
  const note=ambiguous.length?(" "+ambiguous.length+" negara tidak ditampilkan karena memiliki beberapa baris kategori; pilih Klasifikasi untuk mempersempit."): "";
  const unmatched=uniqueRows.length-points.length;
  const unitNote=units.length===1?" Unit: "+units[0]+".":" Unit mengikuti baris sumber.";
  setUnTourismStatus("Layer aktif · "+points.length+" marker negara untuk "+indicator+" ("+year+"). Ukuran marker menunjukkan nilai relatif dalam dataset terpilih; titik memakai koordinat referensi negara/ibu kota, bukan batas wilayah."+unitNote+note+(unmatched?" "+unmatched+" negara dilewati karena koordinat/nama tidak cocok.":""),"success");
 }).catch(error=>setUnTourismStatus("Gagal menyiapkan titik negara: "+error.message,"error"))
 .finally(()=>{showBtn.disabled=false;showBtn.textContent="Tampilkan statistik di peta";});
}
function clearUnTourismLayer(){
 if(state.unTourismLayer){state.unTourismLayer.clearLayers();if(state.map.hasLayer(state.unTourismLayer))state.map.removeLayer(state.unTourismLayer);}
 setUnTourismStatus("Layer UN Tourism disembunyikan. Pin analisis lokasi tidak berubah.");
}
function initUnTourismLayer(){
 state.unTourismLayer=L.layerGroup();
 $("unTourismLoadBtn").addEventListener("click",loadUnTourismDataset);
 $("unTourismShowBtn").addEventListener("click",renderUnTourismLayer);
 $("unTourismClearBtn").addEventListener("click",clearUnTourismLayer);
 loadUnTourismManifest();
}
function initMap(){
 state.map=L.map("potentialMap",{worldCopyJump:true,minZoom:2,maxZoom:18,preferCanvas:true,zoomControl:true}).setView([18,10],2);
 L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(state.map);
 state.poiLayer=L.layerGroup().addTo(state.map);
 state.linkLayer=L.layerGroup().addTo(state.map);
 state.marketLayer=L.layerGroup().addTo(state.map);
 L.control.scale({imperial:false,position:"bottomleft"}).addTo(state.map);
 state.map.on("click",event=>{if(!state.siteContext)setOrigin(event.latlng,true,"Pin peta");});
 setTimeout(()=>state.map.invalidateSize(),150);
}
function setOrigin(latlng,analyze=true,label="Lokasi pin"){
 const lat=Number(latlng.lat),lon=Number(latlng.lng);
 if(!Number.isFinite(lat)||!Number.isFinite(lon)||lat<-90||lat>90||lon<-180||lon>180)return;
 state.origin={lat,lon,label};
 if(!state.originMarker){
  state.originMarker=L.marker([lat,lon],{icon:originIcon(),draggable:!state.siteContext,keyboard:true,title:state.siteContext?"Situs UNESCO terpilih":"Titik potensi — bisa diseret"}).addTo(state.map);
  state.originMarker.bindTooltip(state.siteContext?"Koordinat situs UNESCO terpilih":"Titik potensi · seret untuk memindahkan",{direction:"top",offset:[0,-15]});
  state.originMarker.on("dragend",()=>{const p=state.originMarker.getLatLng();setOrigin(p,true,"Pin yang digeser");});
 }else state.originMarker.setLatLng([lat,lon]);
 $("mapSubtitle").textContent=label+" · "+lat.toFixed(4)+", "+lon.toFixed(4);
 $("overallStatus").textContent="Pin aktif · "+lat.toFixed(3)+", "+lon.toFixed(3);
 setOverall("Pin aktif · analisis titik","green");
 if(analyze)analyzePoint();
}
function cacheRead(key,ttl){try{const o=JSON.parse(sessionStorage.getItem(key)||"null");if(o&&o.savedAt&&Date.now()-o.savedAt<ttl)return o.data;}catch(_){}return null;}
function cacheWrite(key,data){try{sessionStorage.setItem(key,JSON.stringify({savedAt:Date.now(),data}));}catch(_){}}
function osmQuery(lat,lon){
 const around="around:5000,"+lat+","+lon;
 return '[out:json][timeout:28];('+
 'nwr('+around+')["tourism"~"attraction|museum|gallery|viewpoint|theme_park|zoo|aquarium|artwork|picnic_site|hotel|guest_house|hostel|camp_site"];'+
 'nwr('+around+')["historic"~"monument|memorial|ruins|castle|archaeological_site|wayside_shrine"];'+
 'nwr('+around+')["natural"~"beach|waterfall|hot_spring|cave_entrance"];'+
 'nwr('+around+')["leisure"~"park|garden"];'+
 'nwr('+around+')["shop"];'+
 'nwr('+around+')["amenity"~"marketplace|restaurant|cafe|fast_food|food_court|bakery|ice_cream|hotel|guest_house|hostel|car_repair|tailor|community_centre"];'+
 'nwr('+around+')["craft"];'+
 'nwr('+around+')["office"~"company|commercial|wholesale"];'+
 'nwr('+around+')["landuse"~"farmland|orchard|plant_nursery|vineyard"];'+
 ');out center tags;';
}
function osmQueryCompact(lat,lon){
 const around="around:5000,"+lat+","+lon;
 return '[out:json][timeout:16];('+
  'nwr('+around+')["name"]["tourism"~"attraction|museum|gallery|viewpoint|hotel|guest_house|hostel|camp_site"];'+
  'nwr('+around+')["name"]["historic"~"monument|memorial|ruins|castle|archaeological_site|wayside_shrine"];'+
  'nwr('+around+')["name"]["natural"~"beach|waterfall|hot_spring|cave_entrance"];'+
  'nwr('+around+')["name"]["leisure"~"park|garden"];'+
  'nwr('+around+')["name"]["shop"];'+
  'nwr('+around+')["name"]["amenity"~"marketplace|restaurant|cafe|fast_food|food_court|bakery|hotel|guest_house|hostel"];'+
  'nwr('+around+')["name"]["craft"];'+
  'nwr('+around+')["name"]["office"~"company|commercial|wholesale"];'+
  ');out center tags;';
}
async function fetchNearby(lat,lon){
 const cacheKey="gpir:potential-pois:v1:"+lat.toFixed(3)+":"+lon.toFixed(3);
 const cached=cacheRead(cacheKey,POI_CACHE_TTL);
 if(Array.isArray(cached)){state.poiFallbackUsed=false;return cached;}
 const attempts=[
  {endpoint:"https://overpass-api.de/api/interpreter",query:osmQuery(lat,lon),timeout:18000,label:"full query"},
  {endpoint:"https://overpass-api.de/api/interpreter",query:osmQueryCompact(lat,lon),timeout:14000,label:"compact query"},
  {endpoint:"https://overpass.kumi.systems/api/interpreter",query:osmQueryCompact(lat,lon),timeout:14000,label:"alternate Overpass endpoint"}
 ];
 let lastError=null;
 for(let index=0;index<attempts.length;index++){
  const attempt=attempts[index];
  if(Date.now()-state.lastOverpassAt<1200)await new Promise(resolve=>setTimeout(resolve,1200-(Date.now()-state.lastOverpassAt)));
  state.lastOverpassAt=Date.now();
  const controller=new AbortController();let timer=null;
  try{
   const request=fetch(attempt.endpoint+"?data="+encodeURIComponent(attempt.query),{
    headers:{Accept:"application/json"},signal:controller.signal,cache:"no-store"
   }).then(async response=>{
    if(!response.ok)throw new Error("Overpass HTTP "+response.status);
    const payload=await response.json();
    if(!payload||!Array.isArray(payload.elements))throw new Error("Unexpected Overpass response");
    return payload;
   });
   const timeout=new Promise((_,reject)=>{
    timer=setTimeout(()=>{try{controller.abort();}catch(_){}reject(new Error("request timed out after "+Math.round(attempt.timeout/1000)+" seconds"));},attempt.timeout);
   });
   const payload=await Promise.race([request,timeout]);
   const unique=new Map();
   (payload.elements||[]).forEach(el=>{
    const tags=el.tags||{},plat=num(el.lat!=null?el.lat:el.center&&el.center.lat),plon=num(el.lon!=null?el.lon:el.center&&el.center.lon);
    if(plat==null||plon==null)return;
    const distance=km(lat,lon,plat,plon);if(distance>5.01)return;
    const id=el.type+"/"+el.id,name=tags.name||tags.brand||tags.operator||tags.craft||"Lokasi tanpa nama";
    unique.set(id,{id,name,category:poiCategory(tags),lat:plat,lon:plon,distance,tags,source:"OpenStreetMap",url:tags.website||tags["contact:website"]||""});
   });
   const rows=[...unique.values()].sort((a,b)=>a.distance-b.distance);
   cacheWrite(cacheKey,rows);
   state.poiFallbackUsed=index>0;state.poiSearchStrategy=attempt.label;
   return rows;
  }catch(error){lastError=error;}
  finally{if(timer)clearTimeout(timer);try{controller.abort();}catch(_){}}
 }
 throw new Error("All OpenStreetMap Overpass searches failed. Last error: "+String(lastError&&lastError.message||lastError||"unknown error"));
}
async function ensureTradeFeed(){
 if(state.tradeFeed)return state.tradeFeed;
 if(state.tradePromise)return state.tradePromise;
 state.tradePromise=(async()=>{
  const response=await fetch(TRADE_URL,{cache:"no-cache",headers:{Accept:"application/json"}});
  if(!response.ok)throw new Error("Feed perdagangan HTTP "+response.status);
  const payload=await response.json();
  state.tradeFeed=payload;
  state.tradeRows=Array.isArray(payload.items)?payload.items:(Array.isArray(payload.records)?payload.records:(Array.isArray(payload.data)?payload.data:[]));
  state.dataStatus=payload.meta&&payload.meta.mode||"unknown";
  return payload;
 })();
 try{return await state.tradePromise;}finally{state.tradePromise=null;}
}
async function ensureCountryContext(){
 if(state.countryContext)return state.countryContext;
 if(state.contextPromise)return state.contextPromise;
 state.contextPromise=(async()=>{
  if(window.GPIRMarketContext&&typeof window.GPIRMarketContext.load==="function"){
   try{state.countryContext=await window.GPIRMarketContext.load();}catch(_){}
  }
  if(!state.countryContext)state.countryContext={countries:{}};
  return state.countryContext;
 })();
 try{return await state.contextPromise;}finally{state.contextPromise=null;}
}
function marketCoordinates(iso,row){
 const country=state.countryContext&&state.countryContext.countries&&state.countryContext.countries[iso];
 const lat=num(country&&country.latitude)!=null?num(country.latitude):num(row&&row.market_latitude);
 const lon=num(country&&country.longitude)!=null?num(country&&country.longitude):num(row&&row.market_longitude);
 if(lat!=null&&lon!=null)return {lat,lon,name:country&&country.name||row.market_name||iso};
 const fallback=MARKET_FALLBACKS[iso];
 return fallback?{lat:fallback.lat,lon:fallback.lon,name:fallback.name}:null;
}
function expandTerms(raw){
 const base=String(raw||"").split(/[,;\n/]+/).map(v=>clean(v)).filter(v=>v.length>=2);
 const all=new Set(base);
 base.forEach(term=>{
  Object.entries(SYNONYMS).forEach(([key,values])=>{
   if(term===clean(key)||term.includes(clean(key))||clean(key).includes(term))values.forEach(v=>all.add(clean(v)));
  });
 });
 return [...all].filter(t=>t.length>=3).slice(0,60);
}
function selectedOpportunity(){
 const id=$("opportunitySelect").value;
 return id==="auto"?null:state.catalog.find(o=>o.id===id)||null;
}
function buildSearchTerms(){
 const userTerms=expandTerms($("resourceInput").value);
 const opportunity=selectedOpportunity();
 let opportunityTerms=[];
 if(opportunity)opportunityTerms=[...(opportunity.products||[]),...(opportunity.demand_keywords||[]),...(opportunity.resource_keywords||[]),opportunity.title||""];
 else if(userTerms.length){
  const matched=state.catalog.filter(o=>{
   const hay=[o.title,...(o.products||[]),...(o.resource_keywords||[]),...(o.demand_keywords||[])].join(" ");
   return userTerms.some(term=>clean(hay).includes(term)||term.includes(clean(o.title||"")));
  }).slice(0,4);
  opportunityTerms=matched.flatMap(o=>[...(o.products||[]),...(o.demand_keywords||[]),...(o.resource_keywords||[]),o.title||""]);
 }
 return [...new Set([...userTerms,...expandTerms(opportunityTerms.join(","))])].filter(t=>t.length>=3).slice(0,70);
}
function findTradeMatches(terms){
 if(!state.tradeRows.length||!terms.length)return[];
 const countryFilter=$("marketSelect").value;
 const found=state.tradeRows.filter(row=>{
  const iso=String(row.market_iso3||"").toUpperCase();
  if(countryFilter!=="all"&&iso!==countryFilter)return false;
  const name=clean(row.product_name||row.product&&row.product.name||"");
  if(!name)return false;
  return terms.some(term=>name.includes(term)||term.includes(name));
 });
 return found.filter(row=>num(row.latest_import_usd)!=null||num(row.yoy_growth_pct)!=null).sort((a,b)=>{
  const ga=num(a.yoy_growth_pct),gb=num(b.yoy_growth_pct);
  return Number(gb>0)-Number(ga>0)||(gb??-999)-(ga??-999)||(num(b.latest_import_usd)||0)-(num(a.latest_import_usd)||0)||(num(b.latest_year)||0)-(num(a.latest_year)||0);
 });
}
function groupMarketSignals(rows){
 const byMarket=new Map();
 rows.forEach(row=>{
  const iso=String(row.market_iso3||"").toUpperCase();
  if(!iso)return;
  const center=marketCoordinates(iso,row);
  if(!center)return;
  const current=byMarket.get(iso)||{iso,name:row.market_name||center.name,lat:center.lat,lon:center.lon,signals:[],score:0};
  current.signals.push(row);
  const growth=num(row.yoy_growth_pct),value=num(row.latest_import_usd)||0;
  const signalScore=(growth!=null&&growth>0?Math.min(35,15+growth/5):0)+Math.min(20,Math.log10(value+1)*2);
  current.score=Math.max(current.score,signalScore);
  byMarket.set(iso,current);
 });
 const output=[...byMarket.values()].map(m=>{
  m.signals.sort((a,b)=>(num(b.yoy_growth_pct)>0?1:0)-(num(a.yoy_growth_pct)>0?1:0)||(num(b.yoy_growth_pct)??-999)-(num(a.yoy_growth_pct)??-999)||(num(b.latest_import_usd)||0)-(num(a.latest_import_usd)||0));
  m.topSignal=m.signals[0];
  m.productCount=new Set(m.signals.map(r=>r.product_code||r.product_name)).size;
  return m;
 }).sort((a,b)=>b.score-a.score||a.name.localeCompare(b.name));
 const filter=$("marketSelect").value;
 return filter==="all"?output.slice(0,12):output.filter(m=>m.iso===filter);
}
function opportunityScore(opp,terms,pois,marketRows){
 const keywordTerms=[...(opp.resource_keywords||[]),...(opp.products||[]),...(opp.demand_keywords||[]),opp.title||""].map(clean);
 const resourceMatches=terms.filter(term=>keywordTerms.some(k=>k.includes(term)||term.includes(k)));
 const mapCategories=Array.isArray(opp.map_categories)?opp.map_categories:[];
 const localRelevant=pois.filter(p=>mapCategories.includes(p.category)&&p.distance<=5);
 const tourism=pois.filter(p=>p.category==="tourism"&&p.distance<5);
 const tourismPoints=tourism.length?(opp.tourism_fit==="high"?(Math.min(...tourism.map(p=>p.distance))<=1?16:11):opp.tourism_fit==="medium"?(Math.min(...tourism.map(p=>p.distance))<=1?9:6):0):0;
 const localPoints=Math.min(22,localRelevant.filter(p=>p.category!=="tourism").length*3);
 const tradeTerms=expandTerms([...(opp.products||[]),...(opp.demand_keywords||[]),...(opp.resource_keywords||[]),...terms].join(","));
 const matchedTrade=marketRows.filter(row=>tradeTerms.some(t=>clean(row.product_name).includes(t)||t.includes(clean(row.product_name||""))));
 const growthBonus=matchedTrade.some(row=>num(row.yoy_growth_pct)>0)?10:0;
 const tradePoints=matchedTrade.length?Math.min(18,6+matchedTrade.length*2)+growthBonus:0;
 const resourcePoints=Math.min(32,resourceMatches.length*8);
 const raw=resourcePoints+tourismPoints+localPoints+tradePoints;
 return {score:Math.min(100,Math.round(raw/104*100)),resourceMatches,localRelevant,tourism,matchedTrade,tourismPoints,localPoints,tradePoints};
}
function businessTypeLabel(type){return type==="grow"?"Budidaya":type==="service"?"Jasa":"Produk";}
function renderOpportunityCards(terms,tradeMatches){
 const filter=$("opportunitySelect").value;
 const scored=state.catalog.filter(o=>filter==="auto"||o.id===filter).map(opp=>({...opp,_score:opportunityScore(opp,terms,state.pois,tradeMatches)}));
 scored.sort((a,b)=>b._score.score-a._score.score||(num(a.capital_min_idr)||0)-(num(b.capital_min_idr)||0));
 state.opportunities=scored;
 const display=filter==="auto"?scored.slice(0,5):scored;
 $("ideaSummary").textContent=display.length+" ide";
 if(!display.length){$("opportunityResults").innerHTML='<div class="empty">Tidak ada ide pada filter ini.</div>';return;}
 $("opportunityResults").innerHTML=display.map((opp,i)=>{
  const s=opp._score;
  const reasons=[];
  if(s.resourceMatches.length)reasons.push("cocok kata kunci: "+s.resourceMatches.slice(0,3).join(", "));
  if(s.tourism.length&&s.tourismPoints)reasons.push(s.tourism.length+" atraksi wisata dalam 5 km");
  if(s.localRelevant.length)reasons.push(s.localRelevant.length+" titik ekosistem lokal terkait");
  if(s.matchedTrade.length)reasons.push(s.matchedTrade.length+" sinyal impor produk");
  const why=reasons.length?reasons.join(" · "):"Belum ada sinyal spesifik yang cocok; validasi lapangan tetap diperlukan.";
  const tag=opp.business_type==="service"?"Jasa":opp.business_type==="grow"?"Budidaya":"Produk";
  return '<article class="potential-card"><div class="card-top"><h4>'+(i+1)+". "+esc(opp.title)+'</h4><span class="card-tag">'+esc(tag)+'</span></div><p>'+esc(opp.action_summary||opp.rationale||"Ide untuk diuji secara lokal.")+'</p><p class="card-meta">Kecocokan konteks: <b>'+s.score+'/100</b> · Modal indikatif '+esc(moneyIDR(opp.capital_min_idr))+'–'+esc(moneyIDR(opp.capital_max_idr))+'</p><p>'+esc(why)+'</p><div class="card-actions"><button type="button" data-select-opp="'+esc(opp.id)+'">Telusuri potensi</button><a class="btn" style="min-height:28px;padding:5px 7px;font-size:9px" href="./enterprise.html">Buka SME Finder ↗</a></div></article>';
 }).join("");
 $("opportunityResults").querySelectorAll("[data-select-opp]").forEach(btn=>btn.addEventListener("click",()=>{
  $("opportunitySelect").value=btn.dataset.selectOpp;
  analyzePoint();
 }));
}
function moneyIDR(v){if(num(v)==null)return"belum ditentukan";return new Intl.NumberFormat("id-ID",{style:"currency",currency:"IDR",maximumFractionDigits:0}).format(Number(v));}
function markerPopup(title,subtitle,source){return '<div class="potential-popup"><b>'+esc(title)+'</b><small>'+esc(subtitle||"")+'</small><br><small>'+esc(source||"")+'</small></div>';}
function drawLocalMap(terms){
 state.poiLayer.clearLayers();state.linkLayer.clearLayers();state.marketLayer.clearLayers();
 state.localBounds=null;state.globalBounds=null;state.marketBounds={};
 if(!state.origin)return;
 const origin=state.origin;
 const showTour=$("showTourism").checked,showLocal=$("showLocal").checked,showGlobal=$("showInternational").checked;
 const originLL=L.latLng(origin.lat,origin.lon);
 const allPoints=state.pois;
 const boundsLocal=[originLL];
 const relevantCategories=new Set(state.catalog.flatMap(o=>o.map_categories||[]));
 allPoints.forEach(p=>{
  const isTour=p.category==="tourism";
  const allowed=isTour?showTour:showLocal;
  if(!allowed)return;
  const marker=L.marker([p.lat,p.lon],{icon:iconFor(p.category),keyboard:true,title:p.name});
  marker.bindPopup(markerPopup(p.name,poiLabel(p.category)+" · "+distanceLabel(p.distance),p.source));
  marker.addTo(state.poiLayer);
 });
 if(showTour){
  allPoints.filter(p=>p.category==="tourism"&&p.distance<5).forEach(p=>{
   const line=L.polyline([[origin.lat,origin.lon],[p.lat,p.lon]],{color:COLORS.tourism,weight:3,opacity:.92,dashArray:"5 8",className:"tourism-link"});
   line.bindTooltip(p.name+" · "+distanceLabel(p.distance));line.addTo(state.linkLayer);
   boundsLocal.push(L.latLng(p.lat,p.lon));
  });
 }
 if(showLocal){
  const locals=allPoints.filter(p=>p.category!=="tourism"&&p.distance<=5&&relevantCategories.has(p.category)).sort((a,b)=>a.distance-b.distance);
  locals.slice(0,40).forEach(p=>{
   L.polyline([[origin.lat,origin.lon],[p.lat,p.lon]],{color:COLORS[p.category]||COLORS.other,weight:2,opacity:.78,dashArray:"3 8",className:"local-link"}).bindTooltip(p.name+" · "+distanceLabel(p.distance)).addTo(state.linkLayer);
   boundsLocal.push(L.latLng(p.lat,p.lon));
  });
 }
 state.localBounds=boundsLocal.length>1?L.latLngBounds(boundsLocal):null;
 if(showGlobal){
  const globalBounds=[originLL];
  state.marketSignals.forEach(m=>{
   const p=L.latLng(m.lat,m.lon);
   const line=L.polyline([[origin.lat,origin.lon],[m.lat,m.lon]],{color:"#2563eb",weight:3,opacity:.9,dashArray:"5 11",className:"international-link"});
   line.bindTooltip(m.name+" · "+(m.topSignal&&m.topSignal.product_name||"product trade signal")).addTo(state.marketLayer);
   const dest=L.circleMarker([m.lat,m.lon],{radius:7,color:"#fff",weight:2,fillColor:"#2563eb",fillOpacity:.95});
   dest.bindPopup(markerPopup(m.name,m.iso+" · "+m.productCount+" product signal(s)","UN Comtrade / GPIR trade snapshot")).addTo(state.marketLayer);
   globalBounds.push(p);state.marketBounds[m.iso]=L.latLngBounds([originLL,p]);
  });
  state.globalBounds=globalBounds.length>1?L.latLngBounds(globalBounds):null;
 }
 $("tourismCount").textContent=allPoints.filter(p=>p.category==="tourism"&&p.distance<5).length;
 $("localCount").textContent=allPoints.filter(p=>p.category!=="tourism"&&p.distance<=5).length;
 $("marketCount").textContent=state.marketSignals.length;
 $("mapSubtitle").textContent=origin.label+" · "+origin.lat.toFixed(4)+", "+origin.lon.toFixed(4)+" · "+allPoints.length+" titik lokal";
}
function renderLocalCards(){
 const locals=state.pois.filter(p=>p.category==="tourism"&&p.distance<5&&$("showTourism").checked||p.category!=="tourism"&&p.distance<=5&&$("showLocal").checked).sort((a,b)=>a.distance-b.distance).slice(0,12);
 $("localSummary").textContent=locals.length+" titik · radius 5 km";
 if(!locals.length){$("localResults").innerHTML='<div class="empty">Tidak ada titik yang cocok pada data peta untuk radius ini. Ini tidak membuktikan tidak ada usaha atau atraksi lain.</div>';return;}
 $("localResults").innerHTML=locals.map(p=>{
  const tag=p.category==="tourism"?"tourism":"local";
  const type=poiLabel(p.category);
  return '<article class="potential-card"><div class="card-top"><h4>'+esc(p.name)+'</h4><span class="card-tag '+tag+'">'+esc(type)+'</span></div><p class="card-meta">'+distanceLabel(p.distance)+' dari pin · '+esc(p.source)+'</p><div class="card-actions"><button type="button" data-zoom-poi="'+esc(p.id)+'">Zoom to link</button>'+(p.url?'<a class="btn" style="min-height:28px;padding:5px 7px;font-size:9px" target="_blank" rel="noopener" href="'+esc(p.url)+'">Sumber ↗</a>':"")+'</div></article>';
 }).join("");
 $("localResults").querySelectorAll("[data-zoom-poi]").forEach(btn=>btn.addEventListener("click",()=>zoomLocalPoi(btn.dataset.zoomPoi)));
}
function zoomLocalPoi(id){
 const p=state.pois.find(v=>v.id===id);if(!p||!state.origin)return;
 const bounds=L.latLngBounds([[state.origin.lat,state.origin.lon],[p.lat,p.lon]]);
 state.map.fitBounds(bounds,{padding:[45,45],maxZoom:14});
}
function renderMarketCards(){
 const rows=state.marketSignals;
 $("marketSummary").textContent=rows.length+" negara / lokasi tujuan";
 if(!$("showInternational").checked){$("marketResults").innerHTML='<div class="empty">Layer internasional sedang dinonaktifkan.</div>';return;}
 if(!rows.length){$("marketResults").innerHTML='<div class="empty">Belum ada observasi impor yang cocok dalam snapshot GPIR untuk kata kunci ini. Data terbatas bukan bukti bahwa permintaan tidak ada. Untuk Belanda, cek lagi setelah feed Comtrade diperbarui dengan reporter NLD.</div>';return;}
 $("marketResults").innerHTML=rows.map((m,i)=>{
  const top=m.topSignal||{},growth=num(top.yoy_growth_pct),value=num(top.latest_import_usd);
  const status=growth!=null&&growth>0?"Nilai impor naik "+growth.toFixed(1)+"% YoY":growth!=null&&growth<0?"Nilai impor turun "+Math.abs(growth).toFixed(1)+"% YoY":"Belum ada sinyal pertumbuhan YoY yang dapat dibaca";
  return '<article class="potential-card"><div class="card-top"><h4>'+esc(m.name)+'</h4><span class="card-tag trade">'+esc(m.iso)+'</span></div><p><b>'+esc(top.product_name||"Produk cocok")+'</b></p><p class="card-meta">'+esc(status)+' · Tahun '+esc(top.latest_year||"—")+'</p><p>Nilai impor dilaporkan: <b>'+esc(compactUSD(value))+'</b>. Ini arus perdagangan nasional, bukan penjualan lokal atau purchase order.</p><p class="card-meta">'+m.signals.length+' observasi cocok · skor sinyal '+Math.round(m.score)+'</p><div class="card-actions"><button type="button" data-zoom-market="'+esc(m.iso)+'">Zoom to link ↗</button></div></article>';
 }).join("");
 $("marketResults").querySelectorAll("[data-zoom-market]").forEach(btn=>btn.addEventListener("click",()=>zoomMarket(btn.dataset.zoomMarket)));
}
function zoomMarket(iso){
 const bounds=state.marketBounds[iso];
 if(bounds){state.map.fitBounds(bounds,{padding:[45,45],maxZoom:6});return;}
 const m=state.marketSignals.find(x=>x.iso===iso);if(!m||!state.origin)return;
 state.map.fitBounds(L.latLngBounds([[state.origin.lat,state.origin.lon],[m.lat,m.lon]]),{padding:[45,45],maxZoom:6});
}
function renderAll(terms,matchedRows){
 const selectedFilter=$("marketSelect").value;
 const filteredRows=selectedFilter==="all"?matchedRows:matchedRows.filter(row=>String(row.market_iso3||"").toUpperCase()===selectedFilter);
 state.marketSignals=groupMarketSignals(filteredRows);
 renderOpportunityCards(terms,filteredRows);
 drawLocalMap(terms);
 renderLocalCards();
 renderMarketCards();
 $("dataModePill").textContent=state.dataStatus==="live"?"COMTRADE LIVE":state.dataStatus==="preview"?"COMTRADE PREVIEW":String(state.dataStatus||"TRADE DATA").toUpperCase();
 $("dataModePill").className="pill "+(state.dataStatus==="live"?"green":"gold");
}
async function analyzePoint(){
 if(!state.origin){setStatus("Klik peta dunia untuk menaruh pin, atau cari lokasi terlebih dahulu.");return;}
 const seq=++state.analyzeSequence,origin=state.origin;
 const terms=buildSearchTerms();state.lastTerms=terms;
 $("analyzeBtn").disabled=true;$("analyzeBtn").textContent="Menganalisis…";
 setStatus("Mencari titik sekitar dalam 5 km serta memuat sinyal impor yang relevan…");
 setOverall("Analisis berjalan","gold");
 const outcomes=await Promise.allSettled([fetchNearby(origin.lat,origin.lon),ensureTradeFeed(),ensureCountryContext()]);
 if(seq!==state.analyzeSequence)return;
 if(outcomes[0].status==="fulfilled")state.pois=outcomes[0].value;
 else{state.pois=[];console.warn("Nearby map lookup failed",outcomes[0].reason);}
 if(outcomes[1].status==="fulfilled"){
  const feed=outcomes[1].value;
  state.dataStatus=feed.meta&&feed.meta.mode||"unknown";
 }else{state.tradeRows=[];state.dataStatus="unavailable";console.warn("Trade feed unavailable",outcomes[1].reason);}
 if(outcomes[2].status==="rejected")console.warn("Country context unavailable",outcomes[2].reason);
 const finalTerms=buildSearchTerms(),matchedRows=findTradeMatches(finalTerms);
 renderAll(finalTerms,matchedRows);
 const notes=[];
 notes.push(state.pois.length+" titik peta ditemukan dalam radius 5 km");
 notes.push(state.marketSignals.length+" pasar dengan sinyal cocok");
 if(outcomes[0].status==="rejected")notes.push("peta lokal tidak tersedia");
 if(outcomes[1].status==="rejected")notes.push("feed perdagangan tidak tersedia");
 if(!finalTerms.length)notes.push("isi sumber daya untuk menemukan sinyal produk");
 setStatus(notes.join(" · ")+". Periksa sumber dan validasi buyer sebelum investasi.",outcomes[0].status==="fulfilled"?"success":"error");
 setOverall(state.marketSignals.length?"Sinyal lokal & global ditemukan":"Peta dianalisis · sinyal pasar terbatas",state.marketSignals.length?"green":"gold");
 $("analyzeBtn").disabled=false;$("analyzeBtn").textContent="Analisis titik ↗";
}
async function searchLocation(){
 const query=$("locationSearch").value.trim();
 if(query.length<3){setStatus("Masukkan nama tempat yang lebih lengkap, lalu klik Cari lokasi.");return;}
 $("searchLocationBtn").disabled=true;setStatus("Mencari koordinat lokasi…");
 try{
  const key="gpir:potential-geocode:"+clean(query);
  let result=cacheRead(key,30*24*60*60*1000);
  if(!result){
   const response=await fetch("https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q="+encodeURIComponent(query),{headers:{Accept:"application/json"}});
   if(!response.ok)throw new Error("Nominatim HTTP "+response.status);
   const results=await response.json();if(!results.length)throw new Error("Lokasi tidak ditemukan. Coba nama kecamatan/kabupaten dan negara.");
   result=results[0];cacheWrite(key,result);
  }
  setOrigin({lat:Number(result.lat),lng:Number(result.lon)},true,result.display_name||query);
  state.map.setView([Number(result.lat),Number(result.lon)],11);
 }catch(error){setStatus("Pencarian lokasi gagal: "+error.message,"error");}
 finally{$("searchLocationBtn").disabled=false;}
}
function useMyLocation(){
 if(!navigator.geolocation){setStatus("Browser tidak mendukung geolokasi; cari lokasi secara manual.");return;}
 $("myLocationBtn").disabled=true;setStatus("Meminta izin lokasi dari browser…");
 navigator.geolocation.getCurrentPosition(p=>{
  $("myLocationBtn").disabled=false;
  const lat=p.coords.latitude,lon=p.coords.longitude;
  $("locationSearch").value="";
  setOrigin({lat,lng:lon},true,"Lokasi perangkat");
  state.map.setView([lat,lon],12);
 },err=>{
  $("myLocationBtn").disabled=false;
  setStatus(err.code===1?"Izin lokasi tidak diberikan. Cari tempat secara manual.":"Lokasi tidak tersedia. Cari tempat secara manual.","error");
 },{enableHighAccuracy:false,timeout:12000,maximumAge:300000});
}
function zoomLocal(){if(state.localBounds)state.map.fitBounds(state.localBounds,{padding:[40,40],maxZoom:14});else if(state.origin)state.map.setView([state.origin.lat,state.origin.lon],13);}
function zoomGlobal(){if(state.globalBounds)state.map.fitBounds(state.globalBounds,{padding:[40,40],maxZoom:5});else if(state.origin)state.map.setView([state.origin.lat,state.origin.lon],3);}
function clearOrigin(){
 state.analyzeSequence++;
 $("analyzeBtn").disabled=false;$("analyzeBtn").textContent="Analisis titik ↗";
 state.origin=null;state.pois=[];state.marketSignals=[];state.opportunities=[];
 if(state.originMarker){state.map.removeLayer(state.originMarker);state.originMarker=null;}
 state.poiLayer.clearLayers();state.linkLayer.clearLayers();state.marketLayer.clearLayers();
 $("mapSubtitle").textContent="Peta dunia · belum ada titik aktif";
 $("tourismCount").textContent="—";$("localCount").textContent="—";$("marketCount").textContent="—";
 $("opportunityResults").innerHTML='<div class="empty">Letakkan pin lalu klik Analisis titik untuk melihat potensi.</div>';
 $("localResults").innerHTML='<div class="empty">Titik wisata, pasar, perajin, pemasok dan retail akan tampil di sini.</div>';
 $("marketResults").innerHTML='<div class="empty">Masukkan sumber daya atau pilih ide usaha untuk mencari kecocokan dengan data impor.</div>';
 $("dataModePill").textContent="BELUM DIPILIH";setStatus("Pin dihapus. Klik peta untuk memilih titik baru.");setOverall("Peta siap · letakkan pin","gray");
 state.map.setView([18,10],2);
}
function refreshLayers(){
 if(!state.origin)return;
 const terms=buildSearchTerms(),matchedRows=findTradeMatches(terms);
 renderAll(terms,matchedRows);
}
function populateCatalog(){
 $("opportunitySelect").innerHTML='<option value="auto">Otomatis dari sumber daya</option>'+state.catalog.map(o=>'<option value="'+esc(o.id)+'">'+esc(o.title)+'</option>').join("");
}
function readSiteContext(){
 const params=new URLSearchParams(window.location.search);
 if(params.get("context")!=="site")return null;
 const lat=Number(params.get("lat")),lon=Number(params.get("lon"));
 if(!Number.isFinite(lat)||!Number.isFinite(lon)||lat<-90||lat>90||lon<-180||lon>180)return null;
 return {lat,lon,name:params.get("name")||"Selected UNESCO site",country:params.get("country")||"",siteType:params.get("siteType")||"UNESCO designated site"};
}
function applySiteContextUi(){
 const site=state.siteContext;if(!site)return;
 document.body.classList.add("site-context-mode");
 document.title="Local Economy · "+site.name+" | Regional Science";
 $("pageTitle").textContent="Local Economy Explorer";
 $("pageSubtitle").textContent=site.name+(site.country?" · "+site.country:"")+" · selected source coordinates";
 $("heroEyebrow").textContent=site.siteType.toUpperCase()+" · LOCAL ECONOMY";
 $("heroTitle").textContent="Explore the local economy around "+site.name+".";
 $("heroDescription").textContent="This analysis is pinned to the selected UNESCO site. Explore nearby mapped places, services and optional global market signals without choosing another location.";
 const locationField=$("locationSearch").closest(".field");if(locationField)locationField.hidden=true;
 const searchButtons=$("searchLocationBtn").parentElement;if(searchButtons)searchButtons.hidden=true;
 const picker=$("tourism-picker-section");if(picker)picker.hidden=true;
 $("clearPointBtn").hidden=true;
 const firstHeading=document.querySelector(".sidebar-section .side-heading h3");
 if(firstHeading)firstHeading.textContent="01 · Economy & market filters";
}
async function init(){
 if(!window.L){setStatus("Pustaka peta gagal dimuat. Coba muat ulang halaman.","error");return;}
 state.siteContext=readSiteContext();
 initMap();
 if(!state.siteContext){initDesignatedSitePicker();initUnTourismLayer();}
 $("locationSearch").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();searchLocation();}});
 $("searchLocationBtn").addEventListener("click",searchLocation);
 $("myLocationBtn").addEventListener("click",useMyLocation);
 $("analyzeBtn").addEventListener("click",analyzePoint);
 $("clearPointBtn").addEventListener("click",clearOrigin);
 $("zoomLocalBtn").addEventListener("click",zoomLocal);
 $("zoomGlobalBtn").addEventListener("click",zoomGlobal);
 $("resetMapBtn").addEventListener("click",()=>state.map.setView(state.origin?[state.origin.lat,state.origin.lon]:[18,10],state.origin?12:2));
 $("exampleCassavaBtn").addEventListener("click",()=>{$("resourceInput").value="singkong";$("opportunitySelect").value="cassava-snacks";setOrigin({lat:4.6951,lng:96.7494},false,"Demo Aceh (contoh)");state.map.setView([4.6951,96.7494],7);analyzePoint();});
 $("exampleCraftBtn").addEventListener("click",()=>{$("resourceInput").value="bambu, rotan, kerajinan";$("opportunitySelect").value="bamboo-rattan-craft";setOrigin({lat:-7.7956,lng:110.3695},false,"Demo Yogyakarta (contoh)");state.map.setView([-7.7956,110.3695],8);analyzePoint();});
 ["resourceInput","opportunitySelect","marketSelect"].forEach(id=>$(id).addEventListener("change",()=>{if(state.origin)analyzePoint();}));
 ["showTourism","showLocal","showInternational"].forEach(id=>$(id).addEventListener("change",refreshLayers));
 let catalogLoaded=false;
 try{
  const response=await fetch(CATALOG_URL,{cache:"no-cache"});
  if(!response.ok)throw new Error("Katalog HTTP "+response.status);
  const payload=await response.json();state.catalog=Array.isArray(payload.opportunities)?payload.opportunities:[];populateCatalog();catalogLoaded=true;
 }catch(error){setStatus("Katalog usaha tidak dapat dimuat: "+error.message,"error");}
 if(state.siteContext){
  applySiteContextUi();
  const params=new URLSearchParams(window.location.search),resource=params.get("resource");
  if(resource)$("resourceInput").value=resource;
  setOrigin({lat:state.siteContext.lat,lng:state.siteContext.lon},false,state.siteContext.name);
  state.map.setView([state.siteContext.lat,state.siteContext.lon],12);
  analyzePoint();
 }else if(catalogLoaded){
  setStatus("Peta siap. Klik peta untuk drop pin atau pilih contoh singkong/kerajinan; data global dimuat saat titik dianalisis.","success");
 }
}

init();
})();